"""Synthetic recorder regressions: no display, microphone or GPU is opened."""
import io
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import turborec as tr


class ErrorAndDrainTests(unittest.TestCase):
    def test_synthetic_probe_failure_keeps_only_bounded_redacted_diagnostics(self):
        code, detail = tr._run_bounded_command([sys.executable, "-c",
            "import os; os.write(2, b'x' * 1000000); "
            "os.write(2, b'dummy-key driver mismatch'); raise SystemExit(2)"],
            "dummy-key", timeout=8)
        self.assertEqual(code, 2)
        self.assertLessEqual(len(detail), 8192)
        self.assertNotIn("dummy-key", detail)
        self.assertIn("driver mismatch", detail)

    def test_die_retains_reason_with_numeric_cli_status(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            tr.die("GPU driver cannot initialize", 7)
        self.assertEqual(error.exception.code, 7)
        self.assertIn("GPU driver cannot initialize", str(error.exception))

    def test_giant_no_newline_is_drained_and_secret_is_redacted(self):
        # Catch unbounded line buffering and keys straddling read boundaries.
        secret = "dummy'日本-key"
        with subprocess.Popen([sys.executable, "-c",
                "import os; os.write(2, b'x' * 1000000); "
                "os.write(2, \"dummy'日本-key driver failed\".encode())"],
                stderr=subprocess.PIPE) as proc:
            tail = tr._RecorderStderr(proc.stderr, secret)
            proc.wait(timeout=8)
            tail.join()
            text = tail.text()
        self.assertLessEqual(len(text), 8192)
        self.assertIn("driver failed", text)
        self.assertNotIn(secret, text)
        self.assertIn("••••••••", text)

    def test_existing_forwarder_does_not_leak_split_unicode_key(self):
        secret = "日本-key"
        data = ("x" * 255 + secret + " failed").encode()
        with redirect_stderr(io.StringIO()) as output:
            tr._pump_masked_stderr(io.BytesIO(data), secret)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn("••••••••", output.getvalue())


class GuiBoundaryTests(unittest.TestCase):
    def test_cancellation_before_atomic_launch_releases_without_spawning(self):
        cancelled, launch_lock = threading.Event(), threading.Lock()
        ready, done = threading.Event(), threading.Event()
        errors = []
        def validated(si, spec):
            ready.set()
            return tr.RecordPlan("/unused", [("recorder", ["must-not-launch"], "q")])
        def work():
            try:
                tr._prepare_recording(tr.SystemInfo(), tr.RecordSpec("video_only"), cancelled, launch_lock)
            except SystemExit as error:
                errors.append(str(error))
            finally:
                done.set()
        launch_lock.acquire()
        try:
            with mock.patch.object(tr, "build_plan", side_effect=validated), \
                    mock.patch.object(tr.subprocess, "Popen", side_effect=
                        AssertionError("launched after cancellation")):
                worker = threading.Thread(target=work)
                worker.start()
                self.assertTrue(ready.wait(2))
                cancelled.set()
                launch_lock.release()
                self.assertTrue(done.wait(2))
                worker.join()
        finally:
            if launch_lock.locked():
                launch_lock.release()
        self.assertEqual(errors, ["Start cancelled."])

    def test_auto_fallback_plan_exposes_actual_cpu_encoder(self):
        si = tr.SystemInfo(os="linux", display_server="x11", screen="1920x1080",
            gpu_vendor="nvidia", encoders={"h264_nvenc", "libx264"})
        with mock.patch.object(tr, "_hardware_encoder_usable", return_value=False), \
                mock.patch.object(tr, "ensure_dir"):
            plan = tr.build_plan(si, tr.RecordSpec("video_only", codec="h264"))
        self.assertEqual((plan.encoder_name, plan.encoder_kind), ("libx264", "software"))

    def test_close_during_encoder_validation_cancels_before_recorder_launch(self):
        cancelled = threading.Event()
        def validated(si, spec):
            cancelled.set()
            return tr.RecordPlan("/unused", [("recorder", ["must-not-launch"], "q")])
        with mock.patch.object(tr, "build_plan", side_effect=validated), \
                mock.patch.object(tr.subprocess, "Popen", side_effect=
                    AssertionError("launched after cancellation")), \
                self.assertRaises(SystemExit) as error:
            tr._prepare_recording(tr.SystemInfo(), tr.RecordSpec("video_only"), cancelled)
        self.assertIn("cancel", str(error.exception).lower())

    def test_background_validation_reports_reason_on_main_thread(self):
        main_thread = threading.get_ident()
        callbacks = []
        calls = []
        class Root:
            def after(self, delay, callback):
                self_test.assertEqual(threading.get_ident(), main_thread)
                callbacks.append(callback)
        self_test = self
        def work():
            self.assertNotEqual(threading.get_ident(), main_thread)
            with redirect_stderr(io.StringIO()):
                tr.die("NVENC device unavailable")
        def completed(result, error):
            calls.append((threading.get_ident(), result, str(error)))
        tr._gui_run_job(Root(), work, completed)
        deadline = time.monotonic() + 3
        while not calls and time.monotonic() < deadline:
            if callbacks:
                callbacks.pop(0)()
            time.sleep(0.001)
        self.assertEqual(calls, [(main_thread, None, "NVENC device unavailable")])

    def test_failed_nonempty_gui_output_does_not_get_saved_label(self):
        plan = tr.RecordPlan("/unused/header.mkv")
        status = tr._recording_status(plan, 1)
        self.assertNotIn("Saved", status)
        self.assertIn("failed", status.lower())

    def test_successful_gui_output_gets_saved_label(self):
        self.assertIn("Saved ✓", tr._recording_status(tr.RecordPlan("/unused/movie.mkv"), 0))


class RecordingOutcomeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "requires POSIX recorder signals")
    def test_sigint_ignoring_recorder_escalation_does_not_save_header(self):
        wait = subprocess.Popen.wait
        def short_wait(proc, timeout=None):
            return wait(proc, timeout=min(timeout or 1, 0.05))
        with tempfile.TemporaryDirectory() as directory:
            dest = str(Path(directory) / "header.mkv")
            body = "import signal,sys,time; signal.signal(signal.SIGINT, signal.SIG_IGN); " \
                   "open(sys.argv[1], 'wb').write(b'header'); time.sleep(100)"
            plan = tr.RecordPlan(dest, [("synthetic", [sys.executable, "-c", body, dest], "int")],
                                 self_timed=False)
            with mock.patch.object(subprocess.Popen, "wait", short_wait), \
                    mock.patch.object(tr, "open_file") as opener, redirect_stderr(io.StringIO()) as output:
                code = tr.record_plan(plan, duration=0.15, open_when_done=True)
            self.assertNotEqual(code, 0)
            self.assertNotIn("Saved", output.getvalue())
            self.assertFalse(opener.called)
            self.assertTrue(Path(dest).exists())

    def test_cli_ctrl_c_accepts_gracefully_finalized_ffmpeg_signal_status(self):
        real_popen = subprocess.Popen
        children = []
        def launch(*args, **kw):
            proc = real_popen(*args, **kw)
            children.append(proc)
            return proc
        def ctrl_c(_seconds):
            children[0].wait(timeout=3)
            raise KeyboardInterrupt
        with tempfile.TemporaryDirectory() as directory:
            dest = str(Path(directory) / "complete.mkv")
            body = "import sys,time; time.sleep(.05); " \
                   "open(sys.argv[1], 'wb').write(b'frames'); raise SystemExit(255)"
            plan = tr.RecordPlan(dest, [("synthetic", [sys.executable, "-c", body, dest], "q")])
            with mock.patch.object(tr.subprocess, "Popen", side_effect=launch), \
                    mock.patch.object(tr, "time", mock.Mock(monotonic=time.monotonic, sleep=ctrl_c)), \
                    redirect_stderr(io.StringIO()) as output:
                code = tr.record_plan(plan)
            self.assertEqual(code, 0)
            self.assertIn("Saved", output.getvalue())

    def run_plan(self, directory, body, finalize=None, cleanup=None, secret=None):
        destination = str(Path(directory) / "output.mkv")
        plan = tr.RecordPlan(destination,
            [("synthetic", [sys.executable, "-c", body, destination], "q")],
            finalize=finalize, cleanup=cleanup or [], secret=secret)
        with redirect_stderr(io.StringIO()) as output, \
                mock.patch.object(tr, "open_file") as opener:
            code = tr.record_plan(plan, open_when_done=True)
        return code, output.getvalue(), opener.called

    def test_failed_header_output_never_reports_saved_and_exposes_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            code, text, opened = self.run_plan(directory,
                "import sys; open(sys.argv[1], 'wb').write(b'header'); "
                "sys.stderr.write('CUDA_ERROR_SYSTEM_DRIVER_MISMATCH'); sys.exit(2)")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Saved", text)
        self.assertIn("CUDA_ERROR_SYSTEM_DRIVER_MISMATCH", text.split("Recording…")[-1])
        self.assertFalse(opened)

    def test_zero_exit_missing_or_empty_output_is_failure(self):
        for body in ("pass", "import sys; open(sys.argv[1], 'wb').close()"):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                code, text, opened = self.run_plan(directory, body)
                self.assertNotEqual(code, 0)
                self.assertNotIn("Saved", text)
                self.assertFalse(opened)

    def test_success_reports_saved_and_opens_output(self):
        with tempfile.TemporaryDirectory() as directory:
            code, text, opened = self.run_plan(directory,
                "import sys; open(sys.argv[1], 'wb').write(b'frames')")
        self.assertEqual(code, 0)
        self.assertIn("Saved", text)
        self.assertTrue(opened)

    def test_early_signal_exit_is_not_mistaken_for_requested_stream_stop(self):
        plan = tr.RecordPlan("rtmps://example.invalid/dummy",
            [("synthetic", [sys.executable, "-c", "raise SystemExit(255)"], "q")],
            is_stream=True, secret="dummy")
        with redirect_stderr(io.StringIO()) as output:
            code = tr.record_plan(plan)
        self.assertNotEqual(code, 0)
        self.assertIn("255", output.getvalue())

    def test_successful_mux_cleans_intermediates_only_after_output_success(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory) / "scratch"
            scratch.mkdir()
            video = scratch / "video.mkv"
            video.write_bytes(b"frames")
            dest = str(Path(directory) / "output.mkv")
            mux = [sys.executable, "-c", "import sys; open(sys.argv[1], 'wb').write(b'muxed')", dest]
            code, text, opened = self.run_plan(directory, "pass", mux, [str(video), str(scratch)])
            self.assertEqual(code, 0)
            self.assertIn("Saved", text)
            self.assertTrue(opened)
            self.assertFalse(scratch.exists())

    def test_mux_failure_preserves_intermediates_and_redacts_error(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory) / "scratch"
            scratch.mkdir()
            video, audio = scratch / "video.mkv", scratch / "audio.flac"
            video.write_bytes(b"video frames")
            audio.write_bytes(b"audio frames")
            finalize = [sys.executable, "-c",
                "import sys; sys.stderr.write('dummy-secret mux failed'); sys.exit(3)"]
            code, text, opened = self.run_plan(directory, "pass", finalize,
                [str(video), str(audio), str(scratch)], "dummy-secret")
            self.assertTrue(video.exists())
            self.assertTrue(audio.exists())
            self.assertIn(str(video), text)
            self.assertIn("mux failed", text)
            self.assertNotIn("dummy-secret", text)
            self.assertNotIn("Saved", text)
            self.assertFalse(opened)
            self.assertNotEqual(code, 0)

    def test_mux_launch_exception_preserves_intermediates(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mkv"
            video.write_bytes(b"recoverable")
            code, text, _ = self.run_plan(directory, "pass",
                [str(Path(directory) / "missing-mux")], [str(video)])
            self.assertTrue(video.exists())
            self.assertNotEqual(code, 0)
            self.assertNotIn("Saved", text)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFOs")
    def test_failed_pipeline_cleans_fifo_controls_but_preserves_media(self):
        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory) / "scratch"
            scratch.mkdir()
            video, fifo = scratch / "video.mkv", scratch / "video.fifo"
            video.write_bytes(b"recoverable")
            os.mkfifo(fifo)
            plan = tr.RecordPlan(str(Path(directory) / "failed.mkv"),
                [("synthetic", [sys.executable, "-c", "raise SystemExit(1)"], "q")],
                cleanup=[str(scratch)], fifos=[str(fifo)])
            with redirect_stderr(io.StringIO()):
                self.assertNotEqual(tr.record_plan(plan), 0)
            self.assertFalse(fifo.exists())
            self.assertTrue(video.exists())

    def test_launch_failure_display_masks_secret(self):
        plan = tr.RecordPlan("rtmps://example.invalid/dummy-secret",
            [("synthetic", ["/missing/dummy-secret"], "q")], is_stream=True,
            secret="dummy-secret")
        with redirect_stderr(io.StringIO()) as output, self.assertRaises(SystemExit) as error:
            tr.record_plan(plan)
        self.assertNotIn("dummy-secret", output.getvalue())
        self.assertNotIn("dummy-secret", str(error.exception))


class ProfileProbeTests(unittest.TestCase):
    def test_odd_rgb_capture_probe_preserves_pixels_before_padding(self):
        self.si.screen = "641x479"
        commands = []
        def run(command, secret, timeout):
            commands.append(command)
            return 0, ""
        with mock.patch.object(tr, "_run_bounded_command", side_effect=run), \
                mock.patch.object(tr, "ensure_dir"):
            tr.build_command(self.si, self.spec(resolution="native"))
        probe_input = commands[0][commands[0].index("-i") + 1]
        self.assertIn("s=641x479:r=23", probe_input)
        self.assertIn("format=bgra", probe_input)
        self.assertIn("pad=ceil(iw/2)*2:ceil(ih/2)*2", commands[0][commands[0].index("-vf") + 1])

    def setUp(self):
        tr._ENCODER_PROBE_CACHE.clear()
        self.si = tr.SystemInfo(os="linux", display_server="x11", screen="1920x1080",
            gpu_vendor="nvidia", has_gpu=True, ffmpeg="/synthetic/ffmpeg",
            encoders={"h264_nvenc", "libx264"})

    def tearDown(self):
        tr._ENCODER_PROBE_CACHE.clear()

    def spec(self, **kw):
        return tr.RecordSpec(mode="video_only", codec="h264", out_dir="/unused", **kw)

    def test_probe_uses_capture_dimensions_fps_filters_and_best_4k_profile(self):
        commands = []
        def run(cmd, secret, timeout):
            commands.append(cmd)
            return 0, ""
        with mock.patch.object(tr, "_run_bounded_command", side_effect=run, create=True), \
                mock.patch.object(tr, "ensure_dir"):
            command, _ = tr.build_command(self.si, self.spec(backend="gpu"))
        probe = commands[0]
        self.assertIn("color=c=black:s=1920x1080:r=23", probe)
        self.assertIn("-vf", probe)
        self.assertIn("scale=3840:2160", probe[probe.index("-vf") + 1])
        self.assertIn("format=yuv420p", probe[probe.index("-vf") + 1])
        for flag, value in (("-preset", "p6"), ("-cq", "16"),
                            ("-profile:v", "high"), ("-bf", "3"), ("-r", "23")):
            self.assertEqual(probe[probe.index(flag) + 1], value)
            self.assertEqual(command[command.index(flag) + 1], value)

    def test_effective_profile_changes_do_not_reuse_codec_only_cache(self):
        commands = []
        def run(cmd, secret, timeout):
            commands.append(cmd)
            return 0, ""
        with mock.patch.object(tr, "_run_bounded_command", side_effect=run, create=True), \
                mock.patch.object(tr, "ensure_dir"):
            for spec in (self.spec(), self.spec(), self.spec(fps=60),
                         self.spec(quality="compact"), self.spec(resolution="native")):
                tr.build_command(self.si, spec)
        self.assertEqual(len(commands), 4)

    def test_gpu_device_environment_change_rechecks_cached_profile(self):
        commands = []
        def run(command, secret, timeout):
            commands.append(command)
            return 0, ""
        with mock.patch.object(tr, "_run_bounded_command", side_effect=run), \
                mock.patch.object(tr, "ensure_dir"):
            for device in ("0", "0", "1"):
                with mock.patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": device}):
                    tr.build_command(self.si, self.spec())
        self.assertEqual(len(commands), 2)

    def test_vaapi_and_qsv_probe_match_recording_upload_and_device_flags(self):
        for vendor, name, kind, wanted in (
                ("amd", "h264_vaapi", "vaapi", "format=nv12"),
                ("intel", "h264_qsv", "qsv", "hwupload=extra_hw_frames=64")):
            with self.subTest(kind=kind):
                self.si.gpu_vendor = vendor
                self.si.vaapi_device = "/dev/dri/synthetic-device"
                self.si.encoders = {name, "libx264"}
                commands = []
                def run(command, secret, timeout):
                    commands.append(command)
                    return 0, ""
                with mock.patch.object(tr, "_run_bounded_command", side_effect=run), \
                        mock.patch.object(tr, "ensure_dir"):
                    record, _ = tr.build_command(self.si, self.spec(backend="gpu"))
                probe = commands[0]
                self.assertIn(wanted, probe[probe.index("-vf") + 1])
                self.assertIn(wanted, record[record.index("-filter_complex") + 1])
                flag = "-vaapi_device" if kind == "vaapi" else "-init_hw_device"
                value = "/dev/dri/synthetic-device" if kind == "vaapi" else "qsv=hw"
                self.assertEqual(probe[probe.index(flag) + 1], value)
                self.assertEqual(record[record.index(flag) + 1], value)

    def test_vaapi_device_change_rechecks_cached_profile(self):
        self.si.gpu_vendor = "amd"
        self.si.encoders = {"h264_vaapi", "libx264"}
        commands = []
        def run(command, secret, timeout):
            commands.append(command)
            return 0, ""
        with mock.patch.object(tr, "_run_bounded_command", side_effect=run), \
                mock.patch.object(tr, "ensure_dir"):
            for device in ("/dev/dri/one", "/dev/dri/one", "/dev/dri/two"):
                self.si.vaapi_device = device
                tr.build_command(self.si, self.spec())
        self.assertEqual(len(commands), 2)

    def test_native_wayland_probe_uses_wf_quality_without_inventing_ffmpeg_profile(self):
        self.si.display_server = "wayland"
        self.si.gpu_vendor = "intel"
        self.si.vaapi_device = "/dev/dri/synthetic"
        self.si.encoders = {"h264_vaapi", "libx264"}
        self.si.wayland_recorder = "wf-recorder"
        self.si.wl_default_output = "DP-1"
        commands = []
        def run(command, secret, timeout):
            commands.append(command)
            return 0, ""
        with mock.patch.object(tr, "_run_bounded_command", side_effect=run), \
                mock.patch.object(tr, "ensure_dir"):
            plan = tr.build_plan(self.si, self.spec(resolution="native", backend="gpu"))
        probe, record = commands[0], plan.procs[0][1]
        self.assertEqual(probe[probe.index("-qp") + 1], "18")
        self.assertIn("qp=18", record)
        self.assertNotIn("-profile:v", probe)
        self.assertNotIn("-color_primaries", probe)
        self.assertEqual(probe[probe.index("-vf") + 1], "format=nv12,hwupload")

    def test_actual_profile_failure_selects_cpu_for_auto(self):
        def run(cmd, secret, timeout):
            rc = 1 if "-cq" in cmd else 0
            return rc, "unsupported profile"
        with mock.patch.object(tr, "_run_bounded_command", side_effect=run, create=True), \
                mock.patch.object(tr, "ensure_dir"):
            command, _ = tr.build_command(self.si, self.spec())
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")

    def test_explicit_gpu_does_not_silently_record_cpu_and_has_driver_advice(self):
        with mock.patch.object(tr, "_run_bounded_command", return_value=
                (1, "driver mismatch"), create=True), \
                mock.patch.object(tr, "ensure_dir"), redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as error:
            tr.build_command(self.si, self.spec(backend="gpu"))
        self.assertIn("driver mismatch", str(error.exception))
        self.assertRegex(str(error.exception), "Auto|auto")
        self.assertRegex(str(error.exception), "CPU|cpu")

    def test_preview_does_not_run_hardware_profile_probe(self):
        with mock.patch.object(tr.subprocess, "run", side_effect=
                AssertionError("preview must not probe drivers")):
            plan = tr._gui_build_preview(self.si, self.spec())
        self.assertTrue(plan.procs)

    def test_openh264_only_preview_is_tentative_without_blocking_initialization(self):
        self.si.encoders = {"libopenh264"}
        with mock.patch.object(tr.subprocess, "run", side_effect=
                AssertionError("preview must not initialize codecs")):
            plan = tr._gui_build_preview(self.si, self.spec())
        self.assertEqual(plan.procs[0][1][plan.procs[0][1].index("-c:v") + 1], "libopenh264")

    def test_wayland_scaling_actual_backend_is_software(self):
        si = tr.SystemInfo(os="linux", display_server="wayland", screen="1920x1080",
            gpu_vendor="intel", vaapi_device="/dev/dri/renderD128",
            encoders={"h264_vaapi", "libx264"}, wayland_recorder="wf-recorder",
            wl_default_output="DP-1")
        with mock.patch.object(tr, "_hardware_encoder_usable", return_value=True):
            plan = tr.build_plan(si, self.spec(), preview=True)
        self.assertEqual(plan.encoder_kind, "software")
        self.assertEqual(plan.procs[0][1][plan.procs[0][1].index("-c") + 1], "libx264")

    def test_wayland_explicit_gpu_scaling_is_rejected(self):
        si = tr.SystemInfo(os="linux", display_server="wayland", screen="1920x1080",
            gpu_vendor="intel", vaapi_device="/dev/dri/renderD128",
            encoders={"h264_vaapi", "libx264"}, wayland_recorder="wf-recorder",
            wl_default_output="DP-1")
        with mock.patch.object(tr, "_hardware_encoder_usable", return_value=True), \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            tr.build_plan(si, self.spec(backend="gpu"), preview=True)
        self.assertIn("Wayland", str(error.exception))
