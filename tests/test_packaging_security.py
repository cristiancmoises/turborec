"""Offline functional regressions for packaging publication and tool trust."""

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("sh")
BASH = shutil.which("bash")
TOOL_BYTES = f'#!{SHELL}\nprintf tool-ran > "$TOOL_MARKER"\n'.encode("utf-8")
TOOL_SHA256 = hashlib.sha256(TOOL_BYTES).hexdigest()


def executable(path, text):
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def link_tool(directory, name):
    resolved = shutil.which(name)
    if resolved is None:
        raise unittest.SkipTest(f"fixture requires {name}")
    (directory / name).symlink_to(resolved)


@unittest.skipUnless(os.name == "posix" and SHELL, "POSIX packaging script")
class ArchivePublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="turborec-publication-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.tools = self.directory / "tools"
        self.tools.mkdir()
        for name in ("dirname", "basename", "mkdir", "mktemp", "cp", "cmp", "mv", "rm"):
            link_tool(self.tools, name)
        (self.tools / "python3").symlink_to(sys.executable)
        self.scratch = self.directory / "private-tmp"
        self.scratch.mkdir(mode=0o700)
        self.payload = self.directory / "payload.tar"
        self.payload.write_bytes(b"literal tar fixture bytes")
        # Substitute only compression/extraction, not publication or filesystem
        # semantics. Real ZUPT/TAR round trips live in test_release_metadata.py.
        executable(self.tools / "zupt", f"#!{sys.executable}\n" + '''
import os
import sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == "compress":
    Path(args[-2]).write_bytes(b"verified archive:" + Path(args[-1]).read_bytes())
elif args[0] == "test":
    if os.environ.get("FAIL_VALIDATION"):
        sys.exit(1)
elif args[0] == "extract":
    output = Path(args[2])
    output.mkdir()
    (output / "payload.tar").write_bytes(Path(args[3]).read_bytes()[len(b"verified archive:"):])
else:
    sys.exit(2)
''')

    def build(self, output, **overrides):
        env = dict(PATH=str(self.tools), TMPDIR=str(self.scratch), **overrides)
        return subprocess.run(
            [SHELL, str(ROOT / "packaging/build-zupt-archive.sh"), str(self.payload), str(output)],
            env=env, cwd=self.directory, capture_output=True, text=True, timeout=20,
        )

    def assert_staging_clean(self):
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual(list(self.directory.glob(".zupt-build.*")), [])

    def test_directory_destination_fails_without_publishing_inside_it(self):
        output = self.directory / "release.zupt"
        output.mkdir()
        sentinel = output / "keep"
        sentinel.write_bytes(b"untouched")
        result = self.build(output)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(list(output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"untouched")
        self.assert_staging_clean()

    def test_symlink_to_directory_is_replaced_as_exact_leaf(self):
        referenced = self.directory / "referenced"
        referenced.mkdir()
        sentinel = referenced / "keep"
        sentinel.write_bytes(b"untouched")
        output = self.directory / "release.zupt"
        output.symlink_to(referenced, target_is_directory=True)
        result = self.build(output)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(output.is_symlink())
        self.assertEqual(output.read_bytes(), b"verified archive:literal tar fixture bytes")
        self.assertEqual(list(referenced.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"untouched")
        self.assert_staging_clean()

    def test_existing_file_is_replaced_without_changing_open_old_file(self):
        output = self.directory / "release.zupt"
        output.write_bytes(b"previous release")
        with output.open("rb") as previous:
            result = self.build(output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(previous.read(), b"previous release")
        self.assertEqual(output.read_bytes(), b"verified archive:literal tar fixture bytes")
        self.assert_staging_clean()

    def test_missing_python_fails_before_any_archive_work(self):
        (self.tools / "python3").unlink()
        output = self.directory / "new-output-directory" / "release.zupt"
        result = self.build(output)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("python3 is required", result.stderr)
        self.assertFalse(output.parent.exists())
        self.assert_staging_clean()

    def test_failed_validation_preserves_existing_output(self):
        output = self.directory / "release.zupt"
        output.write_bytes(b"previous release")
        result = self.build(output, FAIL_VALIDATION="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), b"previous release")
        self.assert_staging_clean()


@unittest.skipUnless(os.name == "posix" and BASH and SHELL, "Bash packaging resolver")
class AppImageToolIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="turborec-appimage-tool-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.tools = self.directory / "tools"
        self.tools.mkdir()
        for name in ("chmod", "rm", "tr"):
            link_tool(self.tools, name)
        self.cache = self.directory / "cache"
        self.cache.mkdir()
        self.cached_tool = self.cache / "appimagetool-x86_64.AppImage"
        self.download_marker = self.directory / "downloaded"
        self.tool_marker = self.directory / "executed"
        executable(self.tools / "curl", f"#!{sys.executable}\n" + f'''
import os
import sys
from pathlib import Path
args = sys.argv[1:]
Path(os.environ["DOWNLOAD_MARKER"]).write_text("downloaded")
Path(args[args.index("-o") + 1]).write_bytes({TOOL_BYTES!r})
''')
        # Execute production resolver functions, excluding expensive icon and
        # product staging. Only the external download/tool bytes are fixtures.
        source = (ROOT / "packaging/build-appimage.sh").read_text(encoding="utf-8")
        helpers = source[source.index("log()  {"):source.index("\nneed_file() {")]
        resolver = source[source.index("fetch() {"):source.index('\nAPPIMAGETOOL_BIN="')]
        self.harness = "set -euo pipefail\n" + helpers + "\n" + resolver + '''
APPIMAGETOOL_BIN="$(resolve_appimagetool)"
"${APPIMAGETOOL_BIN}"
'''

    def verifier(self, name="sha256sum"):
        if name == "sha256sum" and shutil.which(name):
            link_tool(self.tools, name)
        else:
            # macOS has no GNU sha256sum; some Linux hosts have no shasum.
            # Keep the resolver checks active using real Python SHA-256 and
            # each checksum command's actual argument/output contract.
            executable(self.tools / name, f"#!{sys.executable}\n" + f'''
import hashlib
import sys
from pathlib import Path
args = sys.argv[1:]
if {name!r} == "shasum":
    assert args[:2] == ["-a", "256"]
    args = args[2:]
assert len(args) == 1
print(hashlib.sha256(Path(args[0]).read_bytes()).hexdigest(), args[0])
''')

    def resolve(self, pin=TOOL_SHA256, **overrides):
        env = dict(
            PATH=str(self.tools), TOOLS_DIR=str(self.cache), ARCH="x86_64",
            APPIMAGETOOL_URL="https://fixture.invalid/appimagetool.AppImage",
            APPIMAGETOOL_SHA256=pin, DOWNLOAD_MARKER=str(self.download_marker),
            TOOL_MARKER=str(self.tool_marker), **overrides,
        )
        return subprocess.run(
            [BASH, "-c", self.harness], cwd=self.directory, env=env,
            text=True, capture_output=True, timeout=20,
        )

    def assert_refused_before_download(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.download_marker.exists())
        self.assertFalse(self.tool_marker.exists())
        self.assertFalse(self.cached_tool.exists())

    def test_missing_verifier_refuses_download(self):
        self.assert_refused_before_download(self.resolve())

    def test_missing_pin_normalizer_refuses_download(self):
        self.verifier()
        (self.tools / "tr").unlink()
        self.assert_refused_before_download(self.resolve())

    def test_missing_or_malformed_pin_refuses_download(self):
        self.verifier()
        for pin in ("", "a" * 63, "a" * 65, "g" * 64, "a" * 63 + "\n"):
            with self.subTest(pin=repr(pin)):
                for path in (self.cached_tool, self.download_marker, self.tool_marker):
                    path.unlink(missing_ok=True)
                self.assert_refused_before_download(self.resolve(pin=pin))

    def test_mismatching_download_never_becomes_executable(self):
        self.verifier()
        result = self.resolve(pin="0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.download_marker.exists())
        self.assertFalse(self.tool_marker.exists())
        self.assertFalse(self.cached_tool.exists() and os.access(self.cached_tool, os.X_OK))

    def test_mismatching_managed_cache_is_not_executed(self):
        self.verifier()
        self.cached_tool.write_bytes(TOOL_BYTES)
        self.cached_tool.chmod(0o755)
        result = self.resolve(pin="0" * 64)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.download_marker.exists())
        self.assertFalse(self.tool_marker.exists())

    def test_cached_tool_still_requires_pin_and_verifier(self):
        self.cached_tool.write_bytes(TOOL_BYTES)
        self.cached_tool.chmod(0o755)
        self.assertNotEqual(self.resolve().returncode, 0)
        self.verifier()
        self.assertNotEqual(self.resolve(pin="").returncode, 0)
        self.assertFalse(self.tool_marker.exists())
        self.assertFalse(self.download_marker.exists())

    def test_matching_download_is_verified_and_executed(self):
        self.verifier()
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.tool_marker.read_text(), "tool-ran")
        self.assertTrue(self.download_marker.exists())

    def test_matching_download_supports_bsd_chmod_operand_order(self):
        self.verifier()
        actual_chmod = shutil.which("chmod")
        (self.tools / "chmod").unlink()
        # BSD chmod interprets -- after the mode as a filename. Delegate valid
        # calls to the host chmod so actual file permissions remain exercised.
        executable(self.tools / "chmod", f"#!{sys.executable}\n" + f'''
import os
import sys
args = sys.argv[1:]
if args[:2] == ["+x", "--"]:
    sys.exit("chmod: --: No such file or directory")
os.execv({actual_chmod!r}, [{actual_chmod!r}] + args)
''')
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.tool_marker.read_text(), "tool-ran")

    def test_uppercase_hex_pin_matches_downloaded_bytes(self):
        self.verifier()
        result = self.resolve(pin=TOOL_SHA256.upper())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.tool_marker.read_text(), "tool-ran")

    def test_download_is_not_executable_during_checksum_verification(self):
        permissions = self.directory / "permissions-during-verification"
        executable(self.tools / "sha256sum", f"#!{sys.executable}\n" + f'''
import hashlib
import os
import sys
from pathlib import Path
payload = Path(sys.argv[1])
Path({str(permissions)!r}).write_text("executable" if os.access(payload, os.X_OK) else "nonexecutable")
print(hashlib.sha256(payload.read_bytes()).hexdigest(), sys.argv[1])
''')
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(permissions.read_text(), "nonexecutable")

    def test_matching_nonexecutable_cache_is_verified_without_download(self):
        self.verifier()
        self.cached_tool.write_bytes(TOOL_BYTES)
        self.cached_tool.chmod(0o644)
        result = self.resolve(NO_DOWNLOAD="1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.download_marker.exists())
        self.assertEqual(self.tool_marker.read_text(), "tool-ran")

    def test_shasum_fallback_verifies_matching_download(self):
        self.verifier("shasum")
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.tool_marker.read_text(), "tool-ran")

    def test_shasum_fallback_rejects_mismatching_download(self):
        self.verifier("shasum")
        result = self.resolve(pin="0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.tool_marker.exists())
        self.assertFalse(self.cached_tool.exists() and os.access(self.cached_tool, os.X_OK))

    def test_checksum_command_failure_refuses_execution(self):
        executable(self.tools / "sha256sum", f"#!{SHELL}\nexit 1\n")
        result = self.resolve()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.tool_marker.exists())
        self.assertFalse(self.cached_tool.exists() and os.access(self.cached_tool, os.X_OK))

    def test_no_download_remains_a_hard_stop_when_cache_missing(self):
        self.verifier()
        self.assert_refused_before_download(self.resolve(NO_DOWNLOAD="1"))

    def test_explicit_operator_tool_remains_trusted_without_pin(self):
        operator_tool = self.directory / "operator-tool"
        executable(operator_tool, TOOL_BYTES.decode())
        result = self.resolve(pin="", APPIMAGETOOL=str(operator_tool))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.download_marker.exists())
        self.assertEqual(self.tool_marker.read_text(), "tool-ran")

    def test_operator_path_tool_remains_trusted_without_pin(self):
        executable(self.tools / "appimagetool", TOOL_BYTES.decode())
        result = self.resolve(pin="")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.download_marker.exists())
        self.assertEqual(self.tool_marker.read_text(), "tool-ran")


if __name__ == "__main__":
    unittest.main()
