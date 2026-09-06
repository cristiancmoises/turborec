import argparse
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import turborec as tr


DSHOW_SOURCES = r"""
Auto-detected sources for dshow:
  @device_pnp_\\?\usb#vid_045e&pid_0779\global [Microsoft® LifeCam HD-3000] (video)
  @device_cm_{33D9A762}\wave_{MIC} [Matriz de microfone (Intel® SST)] (audio)
  @device_cm_{33D9A762}\wave_{MIX} [Mixagem estéreo (Realtek Áudio)] (audio)
  @device_pnp_\\?\usb#capture\global [Placa de captura] (video, audio)
"""

DSHOW_LEGACY = r"""
[dshow @ 000001] DirectShow video devices (some may be both video and audio devices)
[dshow @ 000001]  "Câmera HD®" (video)
[dshow @ 000001]     Alternative name "@device_pnp_cam"
[dshow @ 000001] DirectShow audio devices
[dshow @ 000001]  "Matriz de microfone (Intel® SST)" (audio)
[dshow @ 000001]     Alternative name "@device_cm_mic"
"""


class CommandOutputTests(unittest.TestCase):
    def test_decodes_ffmpeg_utf8_instead_of_windows_ansi(self):
        raw = "Câmera 日本語 Intel®".encode("utf-8")
        self.assertEqual(tr._decode_command_output(raw), "Câmera 日本語 Intel®")

    def test_timeout_preserves_partial_device_output(self):
        exc = subprocess.TimeoutExpired(
            ["ffmpeg"], 25, output="Mixagem estéreo".encode("utf-8"))
        with mock.patch.object(tr.subprocess, "run", side_effect=exc):
            self.assertEqual(
                tr.run_cmd(["ffmpeg"], timeout=25), "Mixagem estéreo")


class BsdCapabilityTests(unittest.TestCase):
    def test_each_bsd_has_a_distinct_os_identity(self):
        expected = {
            "FreeBSD": "freebsd",
            "OpenBSD": "openbsd",
            "NetBSD": "netbsd",
            "DragonFly": "dragonfly",
        }
        for reported, detected in expected.items():
            with self.subTest(reported=reported), \
                    mock.patch.object(tr.platform, "system", return_value=reported):
                self.assertEqual(tr.detect_os(), detected)

    def test_ffmpeg_indev_parser_handles_realistic_flags_and_headers(self):
        listing = """
Devices:
 D. = Demuxing supported
 .E = Muxing supported
 ---
 D  sndio           sndio audio capture
 DE oss             OSS (Open Sound System) playback and capture
 DE pulse           Pulse audio output
 D  video4linux2,v4l2 Video4Linux2 device grab
  E caca            caca output device
"""
        self.assertEqual(
            tr._parse_ffmpeg_indevs(listing),
            {"sndio", "oss", "pulse", "video4linux2", "v4l2"},
        )

    def test_bsd_prefers_usable_pulse_with_real_sources(self):
        pulse_mic = tr.AudioDevice(
            "pulse-mic", "Pulse microphone", backend="pulse")
        pulse_result = ([pulse_mic], [], pulse_mic, None)
        with mock.patch.object(tr.shutil, "which", return_value="/usr/bin/pactl"), \
                mock.patch.object(
                    tr, "_detect_audio_linux", return_value=pulse_result), \
                mock.patch.object(tr, "_bsd_audio_nodes") as native_nodes:
            result = tr._detect_audio_bsd(
                "openbsd", {"pulse", "sndio", "oss"})
        self.assertEqual(result, pulse_result)
        native_nodes.assert_not_called()

    def test_openbsd_falls_back_from_unusable_pulse_to_sndio(self):
        def nodes(_os_name, backend):
            return ["/dev/audio0"] if backend == "sndio" else ["/dev/dsp0"]

        with mock.patch.object(tr.shutil, "which", return_value="/usr/bin/pactl"), \
                mock.patch.object(
                    tr, "_detect_audio_linux",
                    return_value=([], [], None, None)), \
                mock.patch.object(tr, "_bsd_audio_nodes", side_effect=nodes):
            mics, monitors, default_mic, default_monitor = \
                tr._detect_audio_bsd("openbsd", {"pulse", "sndio", "oss"})
        self.assertEqual(mics[0].backend, "sndio")
        self.assertEqual(mics[0].id, "/dev/audio0")
        self.assertEqual(monitors, [])
        self.assertIs(default_mic, mics[0])
        self.assertIsNone(default_monitor)

    def test_openbsd_falls_through_missing_sndio_node_to_oss(self):
        with mock.patch.object(tr.shutil, "which", return_value=None), \
                mock.patch.object(
                    tr, "_bsd_audio_nodes",
                    side_effect=lambda _os, backend: (
                        [] if backend == "sndio" else ["/dev/dsp0"])):
            mics, monitors, default_mic, default_monitor = \
                tr._detect_audio_bsd("openbsd", {"sndio", "oss"})
        self.assertEqual(mics[0].backend, "oss")
        self.assertEqual(monitors, [])
        self.assertIs(default_mic, mics[0])
        self.assertIsNone(default_monitor)

    def test_bsd_with_no_real_native_nodes_reports_no_audio(self):
        with mock.patch.object(tr.shutil, "which", return_value=None), \
                mock.patch.object(tr, "_bsd_audio_nodes", return_value=[]):
            result = tr._detect_audio_bsd("freebsd", {"oss", "sndio"})
        self.assertEqual(result, ([], [], None, None))

    def test_other_bsds_prefer_oss_and_auto_mode_uses_only_real_mic(self):
        for os_name in ("freebsd", "netbsd", "dragonfly"):
            with self.subTest(os_name=os_name), \
                    mock.patch.object(tr.shutil, "which", return_value=None), \
                    mock.patch.object(
                        tr, "_bsd_audio_nodes",
                        side_effect=lambda _os, backend: (
                            ["/dev/dsp0"] if backend == "oss" else
                            ["/dev/audio0"])):
                mics, monitors, default_mic, default_monitor = \
                    tr._detect_audio_bsd(os_name, {"sndio", "oss"})
            self.assertEqual(mics[0].backend, "oss")
            self.assertEqual(monitors, [])
            self.assertIsNone(default_monitor)
            self.assertEqual(
                tr._automatic_mode(tr.SystemInfo(
                    os=os_name, default_mic=default_mic)),
                "video_mic",
            )

    def test_native_node_scan_excludes_directories_and_non_devices(self):
        candidates = ["/dev/dsp0", "/dev/sound", "/dev/dspctl"]

        def fake_stat(path):
            if path == "/dev/dsp0":
                return mock.Mock(st_mode=tr.stat.S_IFCHR)
            if path == "/dev/sound":
                return mock.Mock(st_mode=tr.stat.S_IFDIR)
            raise FileNotFoundError(path)

        with mock.patch.object(tr.glob, "glob", return_value=candidates), \
                mock.patch.object(tr.os, "stat", side_effect=fake_stat):
            self.assertEqual(tr._bsd_audio_nodes("freebsd", "oss"),
                             ["/dev/dsp0"])

    def test_audio_args_follow_each_device_backend(self):
        si = tr.SystemInfo(os="freebsd")
        for backend, path in (("pulse", "source"),
                              ("sndio", "/dev/audio0"),
                              ("oss", "/dev/dsp0")):
            with self.subTest(backend=backend):
                args = tr.audio_input_args(
                    si, tr.AudioDevice(path, path, backend=backend))
                self.assertEqual(args[1], backend)
                self.assertEqual(args[-1], path)

    def test_bsd_x11_screen_and_targets_use_existing_x11_path(self):
        enc = tr.EncoderChoice("libx264", "software", "h264")
        si = tr.SystemInfo(
            os="freebsd", display_server="x11", screen="1920x1080")
        with mock.patch.dict(tr.os.environ, {"DISPLAY": ":1"}):
            _pre, args = tr.screen_input_args(
                si, 23, "1280x720+10+20", enc)
        self.assertEqual(args[-1], ":1+10,20")
        self.assertIn("x11grab", args)

        monitors = [
            tr.CaptureTarget("monitor", "one"),
            tr.CaptureTarget("monitor", "two"),
        ]
        windows = [tr.CaptureTarget("window", "terminal")]
        with mock.patch.object(
                tr, "_detect_monitors_x11", return_value=monitors), \
                mock.patch.object(
                    tr, "_detect_windows_x11", return_value=windows):
            targets = tr.detect_capture_targets(si)
        self.assertEqual([target.kind for target in targets],
                         ["screen", "monitor", "monitor", "window"])

    def test_bsd_camera_requires_backend_and_real_device(self):
        spec = tr.RecordSpec(mode="video_only", camera="/dev/video0")
        with self.assertRaises(SystemExit):
            tr.camera_input_args(tr.SystemInfo(os="freebsd"), spec)

        si = tr.SystemInfo(os="freebsd", indevs={"video4linux2", "v4l2"})
        with mock.patch.object(tr, "_is_character_device", return_value=True):
            args = tr.camera_input_args(si, spec)
        self.assertEqual(args[1], "v4l2")
        self.assertEqual(args[-1], "/dev/video0")

        with mock.patch.object(tr.glob, "glob", return_value=["/dev/video0"]), \
                mock.patch.object(tr, "_is_character_device", return_value=True), \
                mock.patch.object(tr, "run_cmd", return_value="640x480"):
            cameras = tr.detect_cameras(si)
        self.assertEqual([(cam.id, cam.label) for cam in cameras],
                         [("/dev/video0", "video0")])

        unavailable = tr.SystemInfo(os="freebsd", indevs={"oss"})
        with mock.patch.object(tr.glob, "glob") as camera_glob:
            self.assertEqual(tr.detect_cameras(unavailable), [])
        camera_glob.assert_not_called()

    def test_explicit_bsd_system_monitor_is_not_invented(self):
        si = tr.SystemInfo(os="freebsd", indevs={"oss"})
        args = argparse.Namespace(
            mic_device=None, system_device="/dev/dsp0")
        with mock.patch.object(
                tr, "_bsd_audio_nodes", return_value=["/dev/dsp0"]), \
                self.assertRaises(SystemExit):
            tr._resolve_audio_devices(si, args)


class DirectShowParserTests(unittest.TestCase):
    def test_structured_sources_keep_unique_ids_labels_and_types(self):
        devices = tr._parse_dshow_sources(DSHOW_SOURCES)
        self.assertEqual(len(devices), 4)
        mic = next(d for d in devices if "Matriz" in d.label)
        self.assertTrue(mic.id.startswith("@device_cm_"))
        self.assertEqual(mic.media_types, {"audio"})
        capture = next(d for d in devices if d.label == "Placa de captura")
        self.assertEqual(capture.media_types, {"audio", "video"})

    def test_legacy_alternative_names_are_paired_not_duplicated(self):
        devices = tr._parse_dshow_list_devices(DSHOW_LEGACY)
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].label, "Câmera HD®")
        self.assertEqual(devices[0].id, "@device_pnp_cam")
        self.assertEqual(devices[1].id, "@device_cm_mic")

    def test_ffmpeg8_inline_listing_without_headings(self):
        text = r"""
[dshow @ 123] "USB Camera" (video)
[dshow @ 123]  Alternative name "@device_pnp_camera"
[dshow @ 123] "Micrófono" (audio)
[dshow @ 123]  Alternative name "@device_cm_microphone"
"""
        devices = tr._parse_dshow_list_devices(text)
        self.assertEqual(
            [(d.label, d.id, d.media_types) for d in devices],
            [
                ("USB Camera", "@device_pnp_camera", {"video"}),
                ("Micrófono", "@device_cm_microphone", {"audio"}),
            ],
        )

    def test_duplicate_friendly_names_remain_distinct_by_id(self):
        text = """
  @device_cm_one [Microphone] (audio)
  @device_cm_two [Microphone] (audio)
"""
        devices = tr._parse_dshow_sources(text)
        self.assertEqual([d.id for d in devices],
                         ["@device_cm_one", "@device_cm_two"])

    def test_ptbr_loopback_is_recognized_but_virtual_mic_is_not(self):
        self.assertTrue(
            tr._is_windows_loopback("Mixagem estéreo (Realtek Áudio)"))
        self.assertFalse(
            tr._is_windows_loopback("Microfone virtual (NVIDIA Broadcast)"))

    def test_audio_and_camera_commands_use_stable_ids(self):
        si = tr.SystemInfo(os="windows")
        dev = tr.AudioDevice("@device_cm_mic", "Matriz de microfone")
        audio = tr.audio_input_args(si, dev)
        self.assertIn("audio=@device_cm_mic", audio)

        spec = tr.RecordSpec(mode="video_only", camera="@device_pnp_camera")
        camera = tr.camera_input_args(si, spec)
        self.assertIn("video=@device_pnp_camera", camera)

    def test_duplicate_gui_labels_keep_both_stable_devices(self):
        devices = [
            tr.AudioDevice("@device_one", "Microphone"),
            tr.AudioDevice("@device_two", "Microphone"),
        ]
        choices = tr._label_choice_map(devices)
        self.assertEqual(list(choices), ["Microphone [1]", "Microphone [2]"])
        self.assertEqual(
            [device.id for device in choices.values()],
            ["@device_one", "@device_two"],
        )


class CaptureTargetTests(unittest.TestCase):
    def setUp(self):
        self.enc = tr.EncoderChoice("libx264", "software", "h264")

    def test_signed_geometry_round_trip(self):
        self.assertEqual(
            tr._parse_geometry("1920x1080-1920+0"),
            ("1920x1080", -1920, 0),
        )
        self.assertEqual(
            tr._parse_wxhxy("800x600+0-600"),
            (800, 600, 0, -600),
        )

    def test_windows_negative_offsets_reach_gdigrab(self):
        si = tr.SystemInfo(os="windows", screen="3840x1080")
        _pre, args = tr.screen_input_args(
            si, 60, "1920x1080-1920+0", self.enc)
        self.assertIn("-1920", args)
        self.assertEqual(args[-1], "desktop")

    def test_x11_negative_offset_keeps_required_plus_separator(self):
        si = tr.SystemInfo(os="linux", display_server="x11")
        with mock.patch.dict(tr.os.environ, {"DISPLAY": ":0.0"}):
            _pre, args = tr.screen_input_args(
                si, 60, "1920x1080-1920+0", self.enc)
        self.assertEqual(args[-1], ":0.0+-1920,0")

    def test_windows_hwnd_is_preferred_over_unicode_title(self):
        si = tr.SystemInfo(os="windows")
        _pre, args = tr.screen_input_args(
            si, 30, None, self.enc,
            win_title="Câmera 日本語", win_hwnd="0x1234")
        self.assertEqual(args[-2:], ["-i", "hwnd=0x1234"])
        self.assertNotIn("title=Câmera 日本語", args)

    @unittest.skipUnless(sys.platform == "win32", "requires Win32 APIs")
    def test_windows_native_monitor_enumeration(self):
        monitors = tr._detect_monitors_windows()
        self.assertTrue(monitors)
        self.assertTrue(monitors[0].geometry)

    def test_macos_uses_enumerated_screen_index(self):
        si = tr.SystemInfo(os="macos")
        _pre, args = tr.screen_input_args(
            si, 30, None, self.enc, screen_device="3")
        self.assertEqual(args[-1], "3:none")

    def test_macos_display_detection_ignores_camera_indices(self):
        video = [
            "0: FaceTime HD Camera",
            "1: OBS Virtual Camera",
            "2: Capture screen 0",
            "3: Capture screen 1",
        ]
        with mock.patch.object(
                tr, "_enumerate_avfoundation", return_value=(video, [])):
            targets = tr._detect_displays_macos("ffmpeg")
        self.assertEqual([t.input_id for t in targets], ["2", "3"])

    def test_macos_region_uses_real_screen_and_crop_filter(self):
        si = tr.SystemInfo(
            os="macos", screen="1920x1080",
            encoders={"libx264"}, ffmpeg="ffmpeg")
        spec = tr.RecordSpec(
            mode="video_only", geometry="800x600+100+50",
            screen_device="3", out_dir="/unused")
        with mock.patch.object(tr, "ensure_dir"):
            cmd, _out = tr.build_command(si, spec)
        self.assertIn("3:none", cmd)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("crop=800:600:100:50", graph)

    def test_malformed_region_fails_instead_of_capturing_full_screen(self):
        si = tr.SystemInfo(os="windows")
        spec = tr.RecordSpec(mode="video_only", region="not-a-region")
        with self.assertRaises(SystemExit):
            tr._validate_capture_geometry(si, spec)


class DefaultsAndShutdownTests(unittest.TestCase):
    def test_video_defaults_are_quality_first_4k_at_23_fps(self):
        spec = tr.RecordSpec(mode="video_only")
        self.assertEqual(
            (spec.quality, spec.codec, spec.fps, spec.resolution),
            ("best", "auto", 23, "4k"),
        )
        args = tr.build_parser().parse_args(["record"])
        self.assertEqual(
            (args.quality, args.codec, args.fps, args.resolution),
            ("best", "auto", 23, "4k"),
        )

    def test_auto_codec_prefers_hardware_av1_over_hevc_and_h264(self):
        si = tr.SystemInfo(
            os="windows", gpu_vendor="nvidia", has_gpu=True,
            encoders={"av1_nvenc", "hevc_nvenc", "h264_nvenc", "libx264"},
        )
        with mock.patch.object(
                tr, "_hardware_encoder_usable", return_value=True):
            choice = tr.choose_encoder(si, "auto")
        self.assertEqual(
            (choice.name, choice.kind, choice.codec),
            ("av1_nvenc", "nvenc", "av1"),
        )

    def test_auto_codec_falls_back_to_realtime_software_h264(self):
        si = tr.SystemInfo(
            os="windows", gpu_vendor="nvidia", has_gpu=True,
            encoders={"av1_nvenc", "hevc_nvenc", "h264_nvenc", "libx264"},
        )
        with mock.patch.object(
                tr, "_hardware_encoder_usable", return_value=False):
            choice = tr.choose_encoder(si, "auto")
        self.assertEqual(
            (choice.name, choice.kind, choice.codec),
            ("libx264", "software", "h264"),
        )

    def test_wayland_auto_codec_uses_same_vaapi_quality_order(self):
        si = tr.SystemInfo(
            os="linux", display_server="wayland", gpu_vendor="intel",
            vaapi_device="/dev/dri/renderD128",
            encoders={"av1_vaapi", "hevc_vaapi", "h264_vaapi", "libx264"},
        )
        spec = tr.RecordSpec(mode="video_only")
        with mock.patch.object(
                tr, "_hardware_encoder_usable", return_value=True):
            codec, _params, kind, _device = tr.wf_codec(si, spec)
        self.assertEqual((codec, kind), ("av1_vaapi", "vaapi"))

    def test_auto_mode_degrades_to_available_sources(self):
        mic = tr.AudioDevice("mic", "Mic")
        mon = tr.AudioDevice("mon", "System", True)
        self.assertEqual(
            tr._automatic_mode(
                tr.SystemInfo(default_mic=mic, default_monitor=mon)),
            "video_both",
        )
        self.assertEqual(
            tr._automatic_mode(tr.SystemInfo(default_mic=mic)), "video_mic")
        self.assertEqual(
            tr._automatic_mode(tr.SystemInfo(default_monitor=mon)),
            "video_system",
        )
        self.assertEqual(
            tr._automatic_mode(tr.SystemInfo()), "video_only")

    def test_auto_mode_uses_manually_resolved_device(self):
        args = tr.build_parser().parse_args(
            ["record", "--mic-device", "@manual_mic", "--dry-run"])
        si = tr.SystemInfo(os="windows")
        captured = {}

        def fake_build(_si, spec, preview=False):
            captured["spec"] = spec
            return tr.RecordPlan("unused", [])

        with mock.patch.object(tr, "probe_system", return_value=si), \
                mock.patch.object(tr, "_resolve_capture_target", return_value=None), \
                mock.patch.object(tr, "build_plan", side_effect=fake_build), \
                mock.patch.object(tr, "record_plan", return_value=0):
            self.assertEqual(tr.cmd_record(args), 0)
        self.assertEqual(captured["spec"].mode, "video_mic")

    def test_linux_without_pactl_does_not_invent_audio_devices(self):
        with mock.patch.object(tr.shutil, "which", return_value=None):
            mics, monitors, default_mic, default_monitor = tr._detect_audio_linux()
        self.assertEqual((mics, monitors, default_mic, default_monitor),
                         ([], [], None, None))

    def test_explicit_missing_system_audio_still_fails(self):
        si = tr.SystemInfo(os="windows", encoders={"libx264"})
        spec = tr.RecordSpec(mode="video_system")
        with self.assertRaises(SystemExit):
            tr.build_plan(si, spec, preview=True)

    def test_ffmpeg_stop_writes_q_instead_of_sending_signal(self):
        proc = mock.Mock()
        proc.poll.return_value = None
        proc.stdin = io.BytesIO()
        tr._signal_stop(proc, "q")
        self.assertEqual(proc.stdin.getvalue(), b"q")
        proc.send_signal.assert_not_called()

    def test_unusable_advertised_hardware_falls_back_to_software(self):
        si = tr.SystemInfo(
            os="windows", gpu_vendor="nvidia",
            encoders={"h264_nvenc", "libx264"})
        with mock.patch.object(
                tr, "_hardware_encoder_usable", return_value=False):
            choice = tr.choose_encoder(si, "h264")
        self.assertEqual((choice.name, choice.kind), ("libx264", "software"))

    def test_hybrid_windows_tries_another_gpu_before_software(self):
        si = tr.SystemInfo(
            os="windows", gpu_vendor="nvidia", has_gpu=True,
            encoders={"h264_nvenc", "h264_qsv", "libx264"})
        with mock.patch.object(
                tr, "_hardware_encoder_usable",
                side_effect=lambda _si, name, _kind: name == "h264_qsv"):
            choice = tr.choose_encoder(si, "h264")
        self.assertEqual((choice.name, choice.kind), ("h264_qsv", "qsv"))


class OpenH264FallbackTests(unittest.TestCase):
    def setUp(self):
        tr._ENCODER_PROBE_CACHE.clear()

    def tearDown(self):
        tr._ENCODER_PROBE_CACHE.clear()

    def test_libx264_stays_preferred_without_an_initialization_probe(self):
        si = tr.SystemInfo(
            os="linux", ffmpeg="/test/ffmpeg",
            encoders={"libx264", "libopenh264"})
        with mock.patch.object(tr.subprocess, "run") as run:
            automatic = tr.choose_encoder(si, "auto", backend="cpu")
            explicit = tr.choose_encoder(si, "h264", backend="cpu")
        self.assertEqual(automatic.name, "libx264")
        self.assertEqual(explicit.name, "libx264")
        run.assert_not_called()

    def test_runtime_usable_openh264_serves_auto_and_explicit_cpu(self):
        si = tr.SystemInfo(
            os="linux", ffmpeg="/test/ffmpeg", encoders={"libopenh264"})
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch.object(
                tr.subprocess, "run", return_value=completed) as run:
            automatic = tr.choose_encoder(si, "auto")
            explicit = tr.choose_encoder(si, "h264", backend="cpu")
        self.assertEqual(
            (automatic.name, automatic.kind, automatic.codec),
            ("libopenh264", "software", "h264"),
        )
        self.assertEqual(explicit.name, "libopenh264")
        self.assertEqual(run.call_count, 1)  # the successful probe is cached

    def test_broken_advertised_openh264_is_rejected_even_when_probes_skipped(self):
        si = tr.SystemInfo(
            os="linux", ffmpeg="/test/ffmpeg", encoders={"libopenh264"})
        completed = subprocess.CompletedProcess([], 1)
        with mock.patch.dict(
                os.environ, {"TURBOREC_SKIP_ENCODER_PROBE": "1"}), \
                mock.patch.object(
                    tr.subprocess, "run", return_value=completed) as run, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                tr.choose_encoder(si, "auto", backend="cpu")
        self.assertIn("libx264/libopenh264", stderr.getvalue())
        self.assertIn("dnf swap noopenh264 openh264", stderr.getvalue())
        probe = run.call_args.args[0]
        self.assertIn("color=c=black:s=256x256:r=1", probe)
        self.assertIn("libopenh264", probe)
        self.assertIn("yuv420p", probe)

    def test_openh264_recording_args_use_supported_quality_bitrate_controls(self):
        enc = tr.EncoderChoice("libopenh264", "software", "h264")
        best = tr.encoder_args(enc, "best", 3840 * 2160 * 23 / 1e6)
        compact = tr.encoder_args(enc, "compact", 3840 * 2160 * 23 / 1e6)
        self.assertEqual(best[best.index("-rc_mode") + 1], "quality")
        self.assertIn("-b:v", best)
        self.assertIn("-maxrate", best)
        self.assertIn("high", best)
        for unsupported in ("-crf", "-preset", "-tune", "-bufsize"):
            self.assertNotIn(unsupported, best)
        best_k = int(best[best.index("-b:v") + 1][:-1])
        compact_k = int(compact[compact.index("-b:v") + 1][:-1])
        self.assertGreater(best_k, compact_k)

    def test_openh264_rtmp_args_use_bitrate_mode_without_x264_options(self):
        enc = tr.EncoderChoice("libopenh264", "software", "h264")
        args = tr._stream_encoder_args(enc, 6800, 23)
        self.assertEqual(args[args.index("-rc_mode") + 1], "bitrate")
        self.assertEqual(args[args.index("-g") + 1], "46")
        self.assertIn("-b:v", args)
        self.assertIn("-maxrate", args)
        self.assertIn("-bf", args)
        for unsupported in ("-crf", "-preset", "-tune", "-bufsize",
                            "-keyint_min"):
            self.assertNotIn(unsupported, args)

    def test_wayland_openh264_params_avoid_x264_only_options(self):
        si = tr.SystemInfo(
            os="linux", display_server="wayland", ffmpeg="/test/ffmpeg",
            encoders={"libopenh264"})
        spec = tr.RecordSpec(mode="video_only", backend="cpu")
        with mock.patch.object(
                tr, "_hardware_encoder_usable", return_value=True):
            codec, params, kind, _device = tr.wf_codec(si, spec)
        self.assertEqual((codec, kind), ("libopenh264", "software"))
        self.assertIn("rc_mode=quality", params)
        self.assertTrue(any(item.startswith("b=") for item in params))
        self.assertFalse(any(
            item.startswith(("crf=", "preset=", "tune=", "bufsize="))
            for item in params))

    def test_wayland_stream_intermediate_uses_openh264_bitrate_mode(self):
        si = tr.SystemInfo(
            os="linux", display_server="wayland", ffmpeg="/test/ffmpeg",
            encoders={"libopenh264"}, wayland_recorder="/usr/bin/wf-recorder",
            wl_default_output="DP-1")
        spec = tr.RecordSpec(
            mode="video_only", backend="cpu",
            stream_url="rtmps://example.invalid/live/key")
        with mock.patch.object(
                tr, "_hardware_encoder_usable", return_value=True):
            plan = tr._build_wayland_plan(
                si, spec, preview=True, out_dir="/unused",
                wants_mic=False, wants_sys=False)
        video_cmd = plan.procs[0][1]
        self.assertEqual(video_cmd[video_cmd.index("-c") + 1], "libopenh264")
        params = [video_cmd[index + 1]
                  for index, arg in enumerate(video_cmd) if arg == "-p"]
        self.assertIn("rc_mode=bitrate", params)
        self.assertFalse(any(
            item.startswith(("crf=", "preset=", "tune=", "bufsize="))
            for item in params))


class DurationParsingTests(unittest.TestCase):
    def test_bare_number_is_seconds(self):
        self.assertEqual(tr.parse_duration("90"), 90.0)
        self.assertEqual(tr.parse_duration("0"), 0.0)

    def test_unit_suffixes(self):
        self.assertEqual(tr.parse_duration("90s"), 90.0)
        self.assertEqual(tr.parse_duration("5m"), 300.0)
        self.assertEqual(tr.parse_duration("1.5h"), 5400.0)

    def test_compound_hms(self):
        self.assertEqual(tr.parse_duration("1h30m"), 5400.0)
        self.assertEqual(tr.parse_duration("1h30m45s"), 5445.0)
        self.assertEqual(tr.parse_duration("1h30s"), 3630.0)

    def test_hour_minute_shorthand(self):
        # "1h30" is the common shorthand for 1h30m, not 1h + 30s.
        self.assertEqual(tr.parse_duration("1h30"), 5400.0)
        self.assertEqual(tr.parse_duration("2h15"), 8100.0)

    def test_clock_format(self):
        self.assertEqual(tr.parse_duration("00:01:30"), 90.0)
        self.assertEqual(tr.parse_duration("1:30"), 90.0)

    def test_bad_durations_raise(self):
        for bad in ("", "abc", "-5m", "1h2h"):
            with self.assertRaises(argparse.ArgumentTypeError):
                tr.parse_duration(bad)


class OutputNamingTests(unittest.TestCase):
    def test_same_second_recordings_do_not_overwrite(self):
        # ffmpeg runs with -y and the timestamp is second-granularity, so a
        # quick second recording must never silently overwrite the first
        # (the first recording's file already exists on disk by then).
        with tempfile.TemporaryDirectory() as d:
            stem = "video_only_2026-08-31_12-00-00"
            p1 = tr._unique_output_path(d, stem, "mkv")
            with open(p1, "w"):  # first recording's file exists
                pass
            p2 = tr._unique_output_path(d, stem, "mkv")
            self.assertEqual(os.path.basename(p2), f"{stem}_1.mkv")
            with open(p2, "w"):
                pass
            p3 = tr._unique_output_path(d, stem, "mkv")
            self.assertEqual(os.path.basename(p3), f"{stem}_2.mkv")

    def test_build_command_output_path_uses_timestamp_stem(self):
        si = tr.SystemInfo(
            os="linux", display_server="x11", screen="1920x1080",
            encoders={"libx264"}, ffmpeg="ffmpeg")
        spec = tr.RecordSpec(mode="video_only", out_dir="/nonexistent-unused")
        with mock.patch.object(tr, "ensure_dir"):
            _cmd, out = tr.build_command(si, spec)
        self.assertRegex(
            out,
            r"/nonexistent-unused/video_only_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.mkv",
        )


if __name__ == "__main__":
    unittest.main()
