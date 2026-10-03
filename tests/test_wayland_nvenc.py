"""Backend contract/planning tests; mocked encode outcomes are not GPU proof."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import turborec as tr


class WaylandNvencTests(unittest.TestCase):
    def setUp(self):
        tr._ENCODER_PROBE_CACHE.clear()
        tr._ENCODER_PROBE_ERRORS.clear()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.real_run = tr.subprocess.run
        self.wf = Path(self.directory.name) / "wf-recorder"
        self.ff = Path(self.directory.name) / "ffmpeg-linked"
        for path in (self.wf, self.ff):
            # Guix build chroots need not contain /bin/sh. Use the interpreter
            # already running the suite; these fixtures really execute.
            path.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n", encoding="utf-8")
            path.chmod(0o700)
        self.si = tr.SystemInfo(os="linux", display_server="wayland", screen="1920x1080",
            gpu_vendor="nvidia", ffmpeg="/unrelated/ffmpeg9",
            encoders={"h264_nvenc", "av1_nvenc", "libx264"},
            wayland_recorder=str(self.wf), wl_default_output="SYNTHETIC-1")

    def paired(self):
        self.si.wayland_ffmpeg = str(self.ff)
        self.si.wayland_encoders = {"h264_nvenc", "libx264"}
        return self.si

    def spec(self, **kwargs):
        return tr.RecordSpec("video_only", codec="h264", out_dir="/unused", **kwargs)

    def run_backend_fixture(self, command, **kwargs):
        # Native Windows cannot execute a POSIX shebang. Adapt only the process
        # boundary; real fixture execution and backend selection/cache stay real.
        if command[0] != str(self.ff):
            raise AssertionError("Probe selected an unrelated backend")
        return self.real_run([sys.executable, *command], **kwargs)

    def test_unidentified_wf_never_inherits_external_nvenc_capability(self):
        with mock.patch.object(tr, "_hardware_encoder_usable", side_effect=
                AssertionError("unrelated FFmpeg cannot validate wf-recorder")), \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            tr.build_plan(self.si, self.spec(backend="gpu"), preview=True)
        self.assertIn("TURBOREC_WF_FFMPEG", str(error.exception))

    def test_matched_backend_uses_nvenc_parameters_and_cpu_frame_conversion(self):
        with mock.patch.object(tr, "_run_bounded_command", return_value=(0, "")) as probe, \
                mock.patch.object(tr, "ensure_dir"):
            plan = tr.build_plan(self.paired(), self.spec(backend="gpu"))
        command = plan.procs[0][1]
        self.assertEqual((plan.encoder_name, plan.encoder_kind), ("h264_nvenc", "nvenc"))
        self.assertEqual(command[0], str(self.wf))
        self.assertNotIn("-d", command)  # VAAPI-only device flag
        for param in ("preset=p6", "cq=16", "rc=vbr", "b=0", "profile=high",
                      "color_primaries=bt709", "color_range=tv"):
            self.assertIn(param, command)
        self.assertEqual(command[command.index("-x") + 1], "yuv420p")
        self.assertIn("scale=3840:2160", command[command.index("-F") + 1])
        self.assertIn("format=yuv420p", command[command.index("-F") + 1])
        synthetic = probe.call_args.args[0]
        self.assertEqual(synthetic[0], str(self.ff))
        self.assertIn("-cq", synthetic)
        self.assertIn("format=yuv420p", synthetic[synthetic.index("-vf") + 1])

    def test_backend_encoder_inventory_not_external_inventory_controls_auto(self):
        self.paired()
        with mock.patch.object(tr, "_run_bounded_command", return_value=(0, "")), \
                mock.patch.object(tr, "ensure_dir"):
            plan = tr.build_plan(self.si, tr.RecordSpec("video_only", out_dir="/unused"))
        self.assertEqual(plan.encoder_name, "h264_nvenc")  # external AV1 is absent in linked FFmpeg

    def test_matched_profile_probe_exercises_cpu_rgb_capture_frames(self):
        with mock.patch.object(tr, "_run_bounded_command", return_value=(0, "")) as probe, \
                mock.patch.object(tr, "ensure_dir"):
            tr.build_plan(self.paired(), self.spec(backend="gpu"))
        command = probe.call_args.args[0]
        self.assertEqual(command[command.index("-i") + 1],
                         "color=c=black:s=1920x1080:r=23,format=bgra")

    def test_paired_cpu_and_444_selection_ignore_opposing_external_inventory(self):
        self.paired()
        self.si.encoders = set()
        for codec, chroma, backend_inventory, wanted in (
                ("h264", "auto", {"libx264"}, "libx264"),
                ("h264", "444", {"libx264"}, "libx264"),
                ("hevc", "auto", {"libx265"}, "libx265"),
                ("hevc", "444", {"libx265"}, "libx265")):
            with self.subTest(codec=codec, chroma=chroma):
                self.si.wayland_encoders = backend_inventory
                spec = tr.RecordSpec("video_only", codec=codec, chroma=chroma, backend="cpu")
                name, _params, kind, _drm = tr.wf_codec(self.si, spec)
                self.assertEqual((name, kind), (wanted, "software"))
        self.assertEqual(self.si.ffmpeg, "/unrelated/ffmpeg9")
        self.assertEqual(self.si.encoders, set())

    def test_paired_missing_software_encoder_is_not_borrowed_from_external_ffmpeg(self):
        self.paired()
        self.si.encoders = {"libx264", "libx265"}
        self.si.wayland_encoders = set()
        for codec, chroma in (("h264", "auto"), ("h264", "444"),
                              ("hevc", "auto"), ("hevc", "444")):
            with self.subTest(codec=codec, chroma=chroma), redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                tr.wf_codec(self.si, tr.RecordSpec("video_only", codec=codec,
                                                  chroma=chroma, backend="cpu"))

    def test_failed_nvenc_auto_fallback_and_openh264_probe_use_actual_backend(self):
        self.paired()
        self.si.encoders = {"libx264"}
        self.si.wayland_encoders = {"h264_nvenc", "libopenh264"}
        with mock.patch.object(tr, "_run_bounded_command", return_value=(1, "NVENC unavailable")), \
                mock.patch.object(tr.subprocess, "run", side_effect=self.run_backend_fixture) as runtime:
            name, _params, kind, _drm = tr.wf_codec(self.si, self.spec())
        self.assertEqual((name, kind), ("libopenh264", "software"))
        self.assertEqual(runtime.call_args.args[0][0], str(self.ff))
        self.assertEqual(self.si.ffmpeg, "/unrelated/ffmpeg9")
        self.assertEqual(self.si.encoders, {"libx264"})

    def test_paired_openh264_initialization_cache_includes_wf_identity(self):
        self.paired()
        self.si.encoders = {"libx264"}
        self.si.wayland_encoders = {"libopenh264"}
        with mock.patch.object(tr.subprocess, "run", side_effect=self.run_backend_fixture) as runtime:
            for changed in (False, False, True):
                if changed:
                    self.wf.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n# replacement backend\n")
                name, _params, kind, _drm = tr.wf_codec(self.si, self.spec(backend="cpu"))
                self.assertEqual((name, kind), ("libopenh264", "software"))
        self.assertEqual(runtime.call_count, 2)

    def test_paired_webcam_intermediate_uses_backend_but_final_encoder_uses_external_ffmpeg(self):
        self.paired()
        self.si.encoders = {"libx265"}
        self.si.wayland_encoders = {"libx264"}
        for chroma in ("auto", "444"):
            with self.subTest(chroma=chroma):
                plan = tr.build_plan(self.si, tr.RecordSpec("video_only", codec="hevc", chroma=chroma,
                    camera="/synthetic-camera", out_dir="/unused"), preview=True)
                capture, compose = plan.procs[0][1], plan.procs[1][1]
                self.assertEqual(capture[capture.index("-c") + 1], "libx264")
                self.assertEqual(capture[capture.index("-x") + 1],
                                 "yuv444p" if chroma == "444" else "yuv420p")
                if chroma == "444":
                    self.assertIn("profile=high444", capture)
                self.assertEqual(compose[0], "/unrelated/ffmpeg9")
                self.assertEqual(compose[compose.index("-c:v") + 1], "libx265")

    def test_failed_profile_falls_back_honestly_for_auto_but_gpu_fails(self):
        self.paired()
        with mock.patch.object(tr, "_run_bounded_command", return_value=(1, "driver mismatch")), \
                mock.patch.object(tr, "ensure_dir"), redirect_stderr(io.StringIO()):
            plan = tr.build_plan(self.si, self.spec())
            self.assertEqual((plan.encoder_name, plan.encoder_kind), ("libx264", "software"))
            with self.assertRaises(SystemExit) as error:
                tr.build_plan(self.si, self.spec(backend="gpu"))
        self.assertIn("driver mismatch", str(error.exception))

    def test_full_profile_cache_includes_both_binary_identities(self):
        self.paired()
        with mock.patch.object(tr, "_run_bounded_command", return_value=(0, "")) as probe, \
                mock.patch.object(tr, "ensure_dir"):
            for spec in (self.spec(), self.spec(), self.spec(fps=60)):
                tr.build_plan(self.si, spec)
            for path in (self.wf, self.ff):
                path.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n# changed identity\n")
                tr.build_plan(self.si, self.spec())
        self.assertEqual(probe.call_count, 4)

    def test_preview_does_not_run_profile_probe(self):
        with mock.patch.object(tr, "_run_bounded_command", side_effect=
                AssertionError("preview cannot validate drivers")):
            plan = tr.build_plan(self.paired(), self.spec(backend="gpu"), preview=True)
        self.assertEqual(plan.encoder_kind, "nvenc")

    def test_composition_gpu_is_rejected_instead_of_labeling_cpu_intermediate_gpu(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tr.build_plan(self.paired(), self.spec(backend="gpu", camera="/synthetic-camera"), preview=True)

    def test_pair_configuration_rejects_partial_relative_or_nonexecutable_paths(self):
        for env in ({"TURBOREC_WF_RECORDER": str(self.wf)},
                    {"TURBOREC_WF_RECORDER": "wf-recorder", "TURBOREC_WF_FFMPEG": str(self.ff)},
                    {"TURBOREC_WF_RECORDER": str(self.wf), "TURBOREC_WF_FFMPEG": "/missing/ffmpeg"}):
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True), \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                tr._configured_wf_pair()

    def test_pair_configuration_preserves_exact_executables(self):
        with mock.patch.dict(os.environ, {"TURBOREC_WF_RECORDER": str(self.wf),
                "TURBOREC_WF_FFMPEG": str(self.ff)}, clear=True):
            self.assertEqual(tr._configured_wf_pair(), (str(self.wf), str(self.ff)))
