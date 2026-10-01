import io
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import turborec as tr


class CommandPreviewPrivacyTests(unittest.TestCase):
    def test_apostrophe_key_is_masked_before_shell_representation_changes(self):
        argv = ["ffmpeg", "-f", "flv", "rtmps://example.invalid/live/dummy'key"]
        rendered = tr._redact_cmd(argv, "dummy'key")
        self.assertEqual(shlex.split(rendered),
                         ["ffmpeg", "-f", "flv", "rtmps://example.invalid/live/••••••••"])
        self.assertEqual(argv[-1], "rtmps://example.invalid/live/dummy'key")

    def test_unicode_spaces_and_repeated_keys_are_masked_in_each_argument(self):
        rendered = tr._redact_cmd(
            ["ffmpeg", "prefix clé'日本 space suffix", "clé'日本 space/clé'日本 space"],
            "clé'日本 space")
        self.assertEqual(shlex.split(rendered),
                         ["ffmpeg", "prefix •••••••• suffix", "••••••••/••••••••"])

    def test_no_secret_preserves_quoted_arguments(self):
        argv = ["ffmpeg", "plain", "a'b", "日本 space", ""]
        for secret in (None, ""):
            with self.subTest(secret=secret):
                self.assertEqual(shlex.split(tr._redact_cmd(argv, secret)), argv)

    def test_dry_run_prints_masked_command_without_launching_a_recorder(self):
        url = "rtmps://example.invalid/live/dummy'key"
        plan = tr.RecordPlan(url, [("ffmpeg", ["never-launch", url], "q")],
                             is_stream=True, secret="dummy'key")
        with redirect_stderr(io.StringIO()) as output:
            self.assertEqual(tr.record_plan(plan, dry_run=True), 0)
        self.assertNotIn("dummy", output.getvalue())
        self.assertIn("••••••••", output.getvalue())


class OutputCollisionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "requires POSIX symlink creation")
    def test_dangling_symlinks_do_not_claim_generated_output_names(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            (directory / "recording.mkv").symlink_to(directory / "missing-target")
            (directory / "recording_1.mkv").symlink_to(directory / "other-missing-target")
            self.assertEqual(tr._unique_output_path(scratch, "recording", "mkv"),
                             str(directory / "recording_2.mkv"))
            self.assertFalse((directory / "missing-target").exists())


class FileOverwritePolicyTests(unittest.TestCase):
    def test_direct_file_recordings_refuse_overwrite_for_video_and_audio(self):
        si = tr.SystemInfo(os="linux", display_server="x11", screen="128x72",
                           encoders={"libx264"}, ffmpeg="ffmpeg")
        mic = tr.AudioDevice(id="dummy.mic", label="Dummy microphone")
        with tempfile.TemporaryDirectory() as scratch:
            for mode in ("video_only", "audio_mic"):
                with self.subTest(mode=mode):
                    spec = tr.RecordSpec(mode=mode, backend="cpu", resolution="native",
                                         out_dir=scratch, mic=mic)
                    command, _ = tr.build_command(si, spec)
                    self.assertIn("-n", command)
                    self.assertNotIn("-y", command)

    def test_streaming_keeps_its_non_file_output_policy(self):
        si = tr.SystemInfo(os="linux", display_server="x11", screen="128x72",
                           encoders={"libx264"}, ffmpeg="ffmpeg")
        url = "rtmps://example.invalid/live/dummy"
        spec = tr.RecordSpec(mode="video_only", backend="cpu", resolution="native",
                             stream_url=url, stream_secret="dummy")
        command, destination = tr.build_command(si, spec)
        self.assertIn("-y", command)
        self.assertNotIn("-n", command)
        self.assertEqual(destination, url)

    def test_wayland_final_mux_refuses_overwrite_but_private_audio_can_overwrite(self):
        si = tr.SystemInfo(os="linux", display_server="wayland", screen="128x72",
                           encoders={"libx264"}, ffmpeg="ffmpeg",
                           wayland_recorder="wf-recorder", wl_default_output="DP-1")
        mic = tr.AudioDevice(id="dummy.mic", label="Dummy microphone")
        spec = tr.RecordSpec(mode="video_mic", backend="cpu", resolution="native",
                             out_dir="/unused-preview", mic=mic, audio_channels="mono")
        plan = tr.build_plan(si, spec, preview=True)
        self.assertIn("-n", plan.finalize)
        self.assertNotIn("-y", plan.finalize)
        audio_command = plan.procs[1][1]
        self.assertIn("-y", audio_command)
        self.assertNotIn("-n", audio_command)

    def test_wayland_composition_refuses_file_overwrite_but_not_streaming(self):
        si = tr.SystemInfo(os="linux", screen="128x72", encoders={"libx264"}, ffmpeg="ffmpeg")
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                target = "rtmps://example.invalid/live/dummy" if streaming else "/unused/output.mkv"
                spec = tr.RecordSpec(mode="video_only", backend="cpu", resolution="native",
                                     camera="/dev/video-dummy", stream_url=target if streaming else None)
                command = tr._ffmpeg_compose_cmd(si, spec, "/unused/screen.fifo", [], target)
                self.assertIn("-y" if streaming else "-n", command)
                self.assertNotIn("-n" if streaming else "-y", command)


class PreviewFilesystemTests(unittest.TestCase):
    def test_preview_plans_do_not_create_recording_directories(self):
        with tempfile.TemporaryDirectory() as scratch:
            for display in ("x11", "wayland"):
                with self.subTest(display=display):
                    destination = Path(scratch) / display
                    si = tr.SystemInfo(os="linux", display_server=display, screen="128x72",
                                       encoders={"libx264"}, ffmpeg="ffmpeg",
                                       wayland_recorder="wf-recorder", wl_default_output="DP-1")
                    spec = tr.RecordSpec(mode="video_only", backend="cpu", resolution="native",
                                         out_dir=str(destination))
                    tr.build_plan(si, spec, preview=True)
                    self.assertFalse(destination.exists())


@unittest.skipUnless(os.name == "posix", "requires POSIX permissions and umask")
class RecordingPermissionTests(unittest.TestCase):
    def test_new_recording_directory_is_private_even_with_permissive_umask(self):
        with tempfile.TemporaryDirectory() as scratch:
            destination = Path(scratch) / "recordings"
            previous_mask = os.umask(0)
            try:
                tr.ensure_dir(str(destination))
            finally:
                os.umask(previous_mask)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)

    def test_existing_recording_directory_permissions_are_not_changed(self):
        with tempfile.TemporaryDirectory() as scratch:
            destination = Path(scratch) / "existing"
            destination.mkdir(mode=0o755)
            destination.chmod(0o755)
            tr.ensure_dir(str(destination))
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o755)

    def test_cli_umask_makes_new_files_private(self):
        with tempfile.TemporaryDirectory() as scratch:
            destination = Path(scratch) / "recording.mkv"
            previous_mask = os.umask(0)
            try:
                # Do not inspect the user's config or enumerate any capture devices.
                with mock.patch.object(tr, "load_config", return_value={}), \
                        mock.patch.object(tr, "_use_bundled_binaries"), \
                        redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_status:
                    tr.main(["--version"])
                self.assertEqual(exit_status.exception.code, 0)
                destination.touch()
            finally:
                os.umask(previous_mask)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)


class WindowsPermissionCompatibilityTests(unittest.TestCase):
    def test_windows_cli_does_not_apply_a_posix_umask(self):
        with mock.patch.object(tr.os, "name", "nt"), \
                mock.patch.object(tr.os, "umask", side_effect=AssertionError("POSIX-only call"), create=True), \
                mock.patch.object(tr, "load_config", return_value={}), \
                mock.patch.object(tr, "_use_bundled_binaries"), \
                redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_status:
            tr.main(["--version"])
        self.assertEqual(exit_status.exception.code, 0)


@unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("bash"),
                     "requires the Linux Bash recorder")
class BashRecordingPrivacyTests(unittest.TestCase):
    def run_functions(self, scratch, commands):
        # Load the real function definitions, stopping before detection/menu dispatch.
        # All recorder calls below use a shell-function fake, never the real FFmpeg.
        source = (Path(tr.__file__).parent / "turborecorder").read_text(encoding="utf-8")
        definitions, boundary, _ = source.partition('\nMODE=""\n')
        self.assertTrue(boundary, "missing Bash dispatch boundary; refusing to run detection")
        script = "umask 0000\n" + definitions + "\n" + commands
        return subprocess.run(
            [shutil.which("bash"), "-c", script, "turborecorder-fixture", str(scratch)],
            cwd=scratch, env={"PATH": os.environ.get("PATH", ""), "HOME": str(scratch)},
            text=True, capture_output=True, timeout=10)

    def test_function_fixture_refuses_a_missing_dispatch_boundary(self):
        with tempfile.TemporaryDirectory() as scratch, \
                mock.patch.object(Path, "read_text", return_value="not a function fixture"), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("unsafe launch")), \
                self.assertRaisesRegex(AssertionError, "dispatch boundary"):
            self.run_functions(Path(scratch), ":")

    def test_new_directory_is_private_without_chmodding_existing_folder(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            existing = directory / "existing"
            existing.mkdir(mode=0o755)
            existing.chmod(0o755)
            result = self.run_functions(directory, '''
umask 0000
ensure_dir "$1/nested/new"
ensure_dir "$1/existing"
: > "$1/caller-file"
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(stat.S_IMODE((directory / "nested").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((directory / "nested/new").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(existing.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE((directory / "caller-file").stat().st_mode), 0o666)

    def test_bash_process_umask_protects_new_files(self):
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            result = self.run_functions(directory, ': > "$1/recording.mkv"')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(stat.S_IMODE((directory / "recording.mkv").stat().st_mode), 0o600)

    def test_all_public_file_recorders_refuse_overwrite_and_create_private_files(self):
        functions = ("audio_internal_only", "audio_microphone_only", "audio_internal_and_mic",
                     "video_without_audio", "video_with_internal_audio", "video_with_microphone",
                     "video_with_both")
        for function in functions:
            with self.subTest(function=function), tempfile.TemporaryDirectory() as scratch:
                directory = Path(scratch)
                result = self.run_functions(directory, r'''
VID_DIR="$1/recordings"; AUD_DIR="$VID_DIR"
AUDIO_EXT=flac; ARESAMPLE=aresample=48000; PAN=stereo
MONITOR_SOURCE=dummy.monitor; MIC_SOURCE=dummy.mic
AUDIO_ARGS=(-c:a flac); PRE_INPUT=(); X11_ARGS=(-f lavfi -i dummy)
VFILTER=format=yuv420p; VENC_ARGS=(-c:v libx264)
timestamp(){ printf fixed; }
ARGV_FILE="$1/argv"
ffmpeg(){ printf '%s\0' "$@" > "$ARGV_FILE"; : > "${@: -1}"; }
''' + function + '\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                argv = (directory / "argv").read_bytes().decode("utf-8").split("\0")[:-1]
                self.assertIn("-n", argv)
                self.assertNotIn("-y", argv)
                self.assertEqual(stat.S_IMODE(Path(argv[-1]).stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
