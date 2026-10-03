"""Run the real legacy launcher with synthetic external binaries, not capture."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"),
                     "Legacy Wayland launcher requires POSIX executable scripts and Bash")
class LegacyWaylandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bin = self.root / "fake-bin"
        self.bin.mkdir()
        self.output = self.root / "recordings"
        self.log = self.root / "wf.json"
        self.probe_log = self.root / "probes.jsonl"
        self.env = {"PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "VID_DIR": str(self.output), "AUD_DIR": str(self.output),
            "XDG_SESSION_TYPE": "wayland", "MONITOR_SOURCE": "synthetic.monitor",
            "MIC_SOURCE": "synthetic.mic", "TEST_WF_LOG": str(self.log),
            "TEST_FF_LOG": str(self.probe_log)}
        self.fixture("nvidia-smi", "print('GPU 0: synthetic')")
        self.fixture("lspci", "print('NVIDIA synthetic')")
        self.fixture("xdpyinfo", "print('dimensions: 640x480 pixels')")
        self.fixture("pactl", "pass")
        self.fixture("wlr-randr", "print('SYNTHETIC-1 \\\"Synthetic\\\"\\n  640x480 px, 60 Hz (current)\\n  Position: 0,0')")
        self.fixture("swaymsg", "print('[]')")
        self.fixture("ffmpeg", self.ff_body())
        self.fixture("wf-recorder", self.wf_body())

    def fixture(self, name, body):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + body + "\n", encoding="utf-8")
        path.chmod(0o700)
        return path

    def ff_body(self):
        return ("import json, os, sys\n"
            "if '-encoders' in sys.argv:\n"
            " print(' V....D libx264 software\\n V....D h264_nvenc synthetic\\n V....D hevc_nvenc synthetic')\n"
            "else:\n"
            " with open(os.environ['TEST_FF_LOG'], 'a') as log: log.write(json.dumps(sys.argv) + '\\n')\n"
            " print('synthetic driver mismatch', file=sys.stderr)\n"
            " sys.exit(int(os.environ.get('TEST_PROBE_FAIL', '0')))\n")

    def wf_body(self):
        return ("import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['TEST_WF_LOG']).write_text(json.dumps(sys.argv))\n"
            "dest = sys.argv[sys.argv.index('-f') + 1]\n"
            "if os.environ.get('TEST_WF_EMPTY') != '1': Path(dest).write_bytes(b'synthetic media')\n"
            "sys.exit(int(os.environ.get('TEST_WF_EXIT', '0')))\n")

    def layout(self, name="checkout", python_name="turborec.py"):
        folder = self.root / name
        folder.mkdir()
        script = folder / "turborecorder"
        shutil.copy2(PROJECT / "turborecorder", script)
        shutil.copy2(PROJECT / "turborec.py", folder / python_name)
        return script

    def pair(self):
        self.env["TURBOREC_WF_RECORDER"] = str(self.fixture("wf-matched", self.wf_body()))
        self.env["TURBOREC_WF_FFMPEG"] = str(self.fixture("ff-matched", self.ff_body()))

    def run_script(self, script, *args, cwd=None):
        return subprocess.run(["bash", str(script), "-m", "video_noaudio", "-o", str(self.output / script.parent.name), *args],
            env=self.env, cwd=cwd, capture_output=True, text=True, timeout=10)

    def shadow_import(self):
        directory = self.root / "untrusted-imports"
        directory.mkdir()
        marker = self.root / "unexpected-import.txt"
        (directory / "shlex.py").write_text(
            f"with open({str(marker)!r}, 'w') as stream: stream.write('unexpected import')\n"
            "raise RuntimeError('UNTRUSTED_SHLEX_WAS_IMPORTED')\n")
        return directory, marker

    def test_wayland_helper_ignores_modules_in_current_directory(self):
        self.pair()
        directory, marker = self.shadow_import()
        result = self.run_script(self.layout(), "-S", cwd=directory)
        self.assertFalse(marker.exists(), result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Saved:', result.stderr)

    def test_wayland_helper_ignores_pythonpath_module_overrides(self):
        self.pair()
        directory, marker = self.shadow_import()
        self.env["PYTHONPATH"] = str(directory)
        result = self.run_script(self.layout(), "-S")
        self.assertFalse(marker.exists(), result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Saved:', result.stderr)

    def test_checkout_and_channel_share_and_guix_hidden_layout_use_exact_pair(self):
        self.pair()
        for name, python_name in (("checkout", "turborec.py"), ("channel-share", "turborec.py"),
                                  ("guix-bin", ".turborec-real")):
            with self.subTest(layout=name):
                script = self.layout(name, python_name)
                if name == "guix-bin":
                    (script.parent / "turborec").write_text(
                        "#!/bin/sh\nraise RuntimeError('shell wrapper must not be loaded')\n")
                result = self.run_script(script, "-f", "23", "-Q", "high", "-C", "hevc")
                self.assertEqual(result.returncode, 0, result.stderr)
                command = json.loads(self.log.read_text())
                self.assertEqual(command[0], self.env["TURBOREC_WF_RECORDER"])
                self.assertEqual(command[command.index('-c') + 1], 'hevc_nvenc')
                self.assertEqual(command[command.index('-r') + 1], '23')
                self.assertIn('cq=19', command)
                self.assertNotIn('-d', command)
                self.assertIn('Saved:', result.stderr)
        probes = [json.loads(line) for line in self.probe_log.read_text().splitlines()]
        self.assertTrue(probes)
        self.assertTrue(all(command[0] == self.env["TURBOREC_WF_FFMPEG"] for command in probes))

    def test_deb_rpm_portable_extensionless_python_payload_uses_exact_pair(self):
        self.pair()
        script = self.layout("installed-bin", "turborec")
        result = self.run_script(script, "-f", "23")
        self.assertEqual(result.returncode, 0, result.stderr)
        command = json.loads(self.log.read_text())
        self.assertEqual(command[0], self.env["TURBOREC_WF_RECORDER"])
        self.assertEqual(command[command.index('-c') + 1], 'h264_nvenc')
        self.assertIn('Saved:', result.stderr)

    def test_shell_wrapper_is_not_imported_as_extensionless_python_payload(self):
        script = self.layout("wrapper-only", "turborec")
        (script.parent / "turborec").write_text(
            "#!/bin/sh\nraise RuntimeError('WRAPPER_WAS_IMPORTED_AS_PYTHON')\n")
        result = self.run_script(script)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn('companion missing', result.stderr.lower())
        self.assertNotIn('WRAPPER_WAS_IMPORTED_AS_PYTHON', result.stderr)
        self.assertFalse(self.log.exists())

    def test_extensionless_engine_symlink_outside_own_directory_is_not_loaded(self):
        script = self.layout("foreign-engine", "turborec")
        (script.parent / "turborec").unlink()
        (script.parent / "turborec").symlink_to(PROJECT / "turborec.py")
        result = self.run_script(script)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn('companion missing', result.stderr.lower())
        self.assertFalse(self.log.exists())

    def test_extensionless_python_interpreter_headers_support_installed_and_env_split_layouts(self):
        self.pair()
        for name, header in (("absolute-python", f"#!{sys.executable}"),
                              ("generic-python", "#!/usr/bin/python"),
                              ("env-split-python", "#!/usr/bin/env -S python3 -Es")):
            with self.subTest(header=header):
                script = self.layout(name, "turborec")
                engine = script.parent / "turborec"
                engine.write_text(header + "\n" + engine.read_text(encoding="utf-8").split("\n", 1)[1],
                                  encoding="utf-8")
                result = self.run_script(script)
                self.assertEqual(result.returncode, 0, result.stderr)
                command = json.loads(self.log.read_text())
                self.assertEqual(command[command.index('-c') + 1], 'h264_nvenc')

    def test_wayland_plan_does_not_require_mapfile_builtin(self):
        self.pair()
        startup = self.root / "bash-startup"
        startup.write_text("enable -n mapfile 2>/dev/null || :\n", encoding="utf-8")
        self.env["BASH_ENV"] = str(startup)
        result = self.run_script(self.layout())
        self.assertEqual(result.returncode, 0, result.stderr)
        command = json.loads(self.log.read_text(encoding="utf-8"))
        self.assertEqual(command[command.index('-c') + 1], 'h264_nvenc')
        self.assertIn('Saved:', result.stderr)

    def test_python2_or_lookalike_header_is_not_imported_as_companion(self):
        for name in ("python2", "python3-helper"):
            with self.subTest(interpreter=name):
                script = self.layout(name, "turborec")
                (script.parent / "turborec").write_text(
                    f"#!/usr/bin/{name}\nraise RuntimeError('FOREIGN_HEADER_IMPORTED')\n",
                    encoding="utf-8")
                result = self.run_script(script)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn('companion missing', result.stderr.lower())
                self.assertNotIn('FOREIGN_HEADER_IMPORTED', result.stderr)
                self.assertFalse(self.log.exists())

    def test_failed_matched_probe_keeps_software_fallback_honest(self):
        self.pair()
        self.env["TEST_PROBE_FAIL"] = "1"
        result = self.run_script(self.layout())
        self.assertEqual(result.returncode, 0, result.stderr)
        command = json.loads(self.log.read_text())
        self.assertEqual(command[command.index('-c') + 1], 'libx264')
        self.assertIn('software', result.stderr)

    def test_unrelated_ffmpeg_missing_encoders_cannot_reject_matched_backend(self):
        self.pair()
        self.fixture("ffmpeg", "print('unrelated FFmpeg has no requested encoders')")
        result = self.run_script(self.layout())
        self.assertEqual(result.returncode, 0, result.stderr)
        command = json.loads(self.log.read_text())
        self.assertEqual(command[command.index('-c') + 1], 'h264_nvenc')

    def test_software_override_uses_paired_inventory_when_external_has_no_encoder(self):
        self.pair()
        self.fixture("ffmpeg", "print('unrelated FFmpeg has no requested encoders')")
        result = self.run_script(self.layout(), "-S")
        self.assertEqual(result.returncode, 0, result.stderr)
        command = json.loads(self.log.read_text())
        self.assertEqual(command[command.index('-c') + 1], 'libx264')
        self.assertIn('software', result.stderr)
        self.assertFalse(self.probe_log.exists())

    def test_existing_output_is_never_overwritten(self):
        self.fixture("date", "print('fixed-timestamp')")
        script = self.layout()
        self.assertEqual(self.run_script(script).returncode, 0)
        destination = next(self.output.rglob('*.mkv'))
        destination.write_bytes(b'existing recoverable recording')
        result = self.run_script(script)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(destination.read_bytes(), b'existing recoverable recording')
        self.assertNotIn('Saved:', result.stderr)

    def test_software_override_preserves_native_60fps_and_avoids_gpu_probe(self):
        self.pair()
        result = self.run_script(self.layout(), "-S")
        self.assertEqual(result.returncode, 0, result.stderr)
        command = json.loads(self.log.read_text())
        self.assertEqual(command[command.index('-c') + 1], 'libx264')
        self.assertEqual(command[command.index('-r') + 1], '60')
        self.assertFalse(self.probe_log.exists())

    def test_requested_capture_size_is_honored_on_wayland(self):
        self.pair()
        result = self.run_script(self.layout(), "-s", "320x240")
        self.assertEqual(result.returncode, 0, result.stderr)
        command = json.loads(self.log.read_text())
        self.assertEqual(command[command.index('-g') + 1], '0,0 320x240')

    def test_backend_failure_never_reports_saved_and_keeps_media(self):
        self.env["TEST_WF_EXIT"] = "2"
        result = self.run_script(self.layout())
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertNotIn('Saved:', result.stderr)
        self.assertTrue(list(self.output.rglob('*.mkv')))

    def test_empty_success_is_failure_without_saved_claim(self):
        self.env["TEST_WF_EMPTY"] = "1"
        result = self.run_script(self.layout())
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Saved:', result.stderr)

    def test_missing_exact_python_sibling_fails_actionably_without_capture(self):
        script = self.layout()
        (script.parent / "turborec.py").unlink()
        self.fixture("turborec", "raise RuntimeError('PATH engine must not be loaded')")
        result = self.run_script(script)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn('companion', result.stderr.lower())
        self.assertFalse(self.log.exists())
