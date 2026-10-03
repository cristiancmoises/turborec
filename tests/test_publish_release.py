"""Offline functional tests for verified release mirroring (not audit evidence)."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAG = "v3.10.0"
ORIGIN = "https://git.securityops.com.br"
DUMMY_TOKEN = "offline_dummy_token"
ASSET_NAMES = (
    "SHA256SUMS",
    "Turbo_Recorder-3.10.0-windows-x64.exe",
    "Turbo_Recorder-3.10.0-windows-x64-setup.exe",
    "Turbo_Recorder-3.10.0-x86_64.AppImage",
    "turborec-3.10.0-1.noarch.rpm",
    "turborec-3.10.0-1.src.rpm",
    "turborec-3.10.0-guix-x86_64.zupt",
    "turborec-3.10.0.pkg",
    "turborec-3.10.0-source.zupt",
    "turborec-3.10.0.zupt",
    "turborec_3.10.0_all.deb",
)

# Only the external transport is replaced: the publisher, JSON parsing,
# checksum validation, scratch lifecycle, and byte comparison remain real.
FAKE_CURL = r'''
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

root = Path(os.environ["FAKE_CURL_ROOT"])
state_path = root / "state.json"
state = json.loads(state_path.read_text())
args = sys.argv[1:]
url = args[-1]
config = sys.stdin.read() if "--config" in args else ""
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps({"argv": args, "stdin": config, "url": url}) + "\n")
parsed = urlsplit(url)
origin = parsed.scheme + "://" + parsed.netloc
if origin != state["origin"]:
    sys.exit(22)  # Never delegate to a real transport.
base = "/api/v1/repos/" + state["owner"] + "/turborec"
method = args[args.index("-X") + 1] if "-X" in args else "GET"

def save():
    state_path.write_text(json.dumps(state))

def assets():
    return [{"id": index + 1, "name": name,
             "size": (root / "remote" / name).stat().st_size,
             "browser_download_url": state["urls"].get(
                 name, state["origin"] + "/attachments/" + name)}
            for index, name in enumerate(state["names"])
            if (root / "remote" / name).is_file()]

if parsed.path == base + "/releases/tags/v3.10.0":
    if not state["exists"]:
        sys.exit(22)
    print(json.dumps({"id": 42, "tag_name": "v3.10.0", "assets": assets()}))
elif parsed.path == base + "/releases" and method == "POST":
    state["created"] = json.loads(args[args.index("-d") + 1])
    state["exists"] = True
    save()
    print(json.dumps({"id": 42, "assets": []}))
elif parsed.path == base + "/releases/42":
    state["metadata_reads"] += 1
    save()
    if state.get("fail_final_metadata") and state["metadata_reads"] >= 2:
        sys.exit(22)
    print(json.dumps({"id": 42, "tag_name": "v3.10.0", "assets": assets()}))
elif parsed.path == base + "/releases/42/assets" and method == "POST":
    name = parse_qs(parsed.query)["name"][0]
    if state.get("reject_upload") == name:
        print("403", end="")
        sys.exit(0)
    source = args[args.index("-F") + 1].split(";", 1)[0].removeprefix("attachment=@")
    shutil.copyfile(source, root / "remote" / name)
    if state.get("corrupt_upload") == name:
        target = root / "remote" / name
        content = target.read_bytes()
        target.write_bytes(bytes([content[0] ^ 1]) + content[1:])
    state.setdefault("uploaded", []).append(name)
    save()
    print("201", end="")
elif parsed.path.startswith("/attachments/"):
    name = unquote(parsed.path.removeprefix("/attachments/"))
    if name not in state["names"] or state.get("fail_download") == name:
        sys.exit(22)
    shutil.copyfile(root / "remote" / name, args[args.index("-o") + 1])
else:
    sys.exit(22)
'''


@unittest.skipUnless(
    os.name == "posix" and shutil.which("bash") and shutil.which("sh"),
    "publisher requires POSIX Bash tools",
)
class PublishReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="turborec-publisher-test-")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.assets = self.workspace / "assets"
        self.remote = self.workspace / "remote"
        self.bin = self.workspace / "bin"
        self.scratch = self.workspace / "scratch"
        for directory in (self.assets, self.remote, self.bin, self.scratch):
            directory.mkdir()
        checksums = []
        for name in ASSET_NAMES[1:]:
            content = ("verified local fixture: " + name + "\n").encode()
            (self.assets / name).write_bytes(content)
            checksums.append(hashlib.sha256(content).hexdigest() + "  " + name + "\n")
        (self.assets / "SHA256SUMS").write_text("".join(checksums))
        for name in ASSET_NAMES:
            (self.remote / name).write_bytes((self.assets / name).read_bytes())
        self.state = {
            "origin": ORIGIN, "owner": "cristiancmoises", "names": list(ASSET_NAMES),
            "exists": True, "urls": {}, "metadata_reads": 0,
        }
        curl = self.bin / "curl"
        curl.write_text("#!" + sys.executable + " -I\n" + FAKE_CURL)
        curl.chmod(0o700)
        # Exercise the same Python version that runs each CI matrix job.
        (self.bin / "python3").symlink_to(sys.executable)
        gh = self.bin / "gh"
        gh.write_text("#!" + shutil.which("sh") + "\nprintf '%s\\n' 'Offline release notes'\n")
        gh.chmod(0o700)
        # Do not inherit forge, GitHub, proxy, or credential environment values.
        self.environment = {
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", os.defpath),
            "FJTOKEN": DUMMY_TOKEN, "CBTOKEN": "", "TMPDIR": str(self.scratch),
            "FAKE_CURL_ROOT": str(self.workspace), "LC_ALL": "C",
        }

    def publish(self):
        (self.workspace / "state.json").write_text(json.dumps(self.state))
        original_files = set(path.name for path in self.assets.iterdir())
        result = subprocess.run(
            ["bash", str(ROOT / "packaging/publish-release.sh"), TAG, str(self.assets)],
            cwd=self.workspace, env=self.environment, input="", capture_output=True,
            text=True, timeout=30,
        )
        self.assertNotIn(DUMMY_TOKEN, result.stdout + result.stderr)
        self.assertEqual(list(self.scratch.iterdir()), [], "private downloads leaked")
        self.assertEqual(set(path.name for path in self.assets.iterdir()), original_files)
        return result

    def calls(self):
        path = self.workspace / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def public_calls(self):
        return [call for call in self.calls() if "/api/v1/" not in call["url"]]

    def shadow_module(self, directory, module):
        marker = self.workspace / (module + "-imported")
        (directory / (module + ".py")).write_text(
            "open(" + repr(str(marker)) + ", 'w').write('fixture imported')\n"
            "raise RuntimeError('unexpected ambient fixture import')\n"
        )
        return marker

    def test_working_directory_modules_do_not_replace_publisher_imports(self):
        for module in ("hashlib", "json"):
            with self.subTest(module=module):
                marker = self.shadow_module(self.workspace, module)
                result = self.publish()
                (self.workspace / (module + ".py")).unlink()
                self.assertFalse(marker.exists(), result.stdout + result.stderr)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pythonpath_modules_do_not_replace_publisher_imports(self):
        imports = self.workspace / "imports"
        imports.mkdir()
        self.environment["PYTHONPATH"] = str(imports)
        for module in ("hashlib", "json"):
            with self.subTest(module=module):
                marker = self.shadow_module(imports, module)
                result = self.publish()
                (imports / (module + ".py")).unlink()
                self.assertFalse(marker.exists(), result.stdout + result.stderr)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_same_size_changed_remote_bytes_are_rejected(self):
        # The checksum file itself is part of the identity contract, too.
        for name in ("SHA256SUMS", ASSET_NAMES[1]):
            with self.subTest(name=name):
                content = (self.remote / name).read_bytes()
                (self.remote / name).write_bytes(bytes([content[0] ^ 1]) + content[1:])
                result = self.publish()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(name, result.stderr)
                (self.remote / name).write_bytes(content)

    def test_identical_rerun_downloads_and_compares_every_asset_without_auth(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        downloads = self.public_calls()
        self.assertEqual({call["url"].rsplit("/", 1)[-1] for call in downloads}, set(ASSET_NAMES))
        self.assertEqual(len(downloads), 11)
        for call in self.calls():
            args = call["argv"]
            self.assertEqual(args[0], "--disable", "user curlrc was not suppressed")
            self.assertNotIn(DUMMY_TOKEN, " ".join(args))
            self.assertEqual(args[args.index("--proto") + 1], "=https")
            if call in downloads:
                self.assertEqual(call["stdin"], "")
                self.assertNotIn("--config", args)
                self.assertNotIn("Authorization", " ".join(args))
                self.assertEqual(args[args.index("--proto-redir") + 1], "=https")
                for option in ("--retry", "--connect-timeout", "--max-time"):
                    self.assertGreater(int(args[args.index(option) + 1]), 0)
            else:
                self.assertEqual(call["stdin"], 'header = "Authorization: token offline_dummy_token"\n')
                self.assertFalse(any(arg in ("-L", "--location", "--location-trusted") for arg in args))
        self.assertFalse(any("POST" in call["argv"] for call in self.calls()))

    def test_foreign_or_userinfo_download_url_is_rejected_before_transport(self):
        for url in (
            "https://foreign.invalid/asset", "https://git.securityops.com.br.evil.invalid/asset",
            "https://user@git.securityops.com.br/asset", "http://git.securityops.com.br/asset",
        ):
            with self.subTest(url=url):
                self.state["urls"][ASSET_NAMES[1]] = url
                result = self.publish()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(any(call["url"] == url for call in self.calls()))

    def test_missing_download_url_fails_closed(self):
        self.state["urls"][ASSET_NAMES[1]] = None
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_public_download_http_failure_fails_verification(self):
        self.state["fail_download"] = ASSET_NAMES[1]
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_final_metadata_http_failure_fails_verification(self):
        self.state["fail_final_metadata"] = True
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_created_release_preserves_notes_and_verifies_uploaded_bytes(self):
        self.state["exists"] = False
        for name in ASSET_NAMES:
            (self.remote / name).unlink()
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = json.loads((self.workspace / "state.json").read_text())
        self.assertEqual(state["created"], {
            "tag_name": TAG, "name": "Turbo Recorder 3.10.0",
            "body": "Offline release notes", "draft": False, "prerelease": False,
        })
        self.assertEqual(set(state["uploaded"]), set(ASSET_NAMES))
        self.assertEqual(len(self.public_calls()), 11)
        for name in ASSET_NAMES:
            self.assertEqual((self.remote / name).read_bytes(), (self.assets / name).read_bytes())

    def test_successful_upload_with_changed_remote_bytes_is_rejected(self):
        name = ASSET_NAMES[1]
        (self.remote / name).unlink()
        self.state["corrupt_upload"] = name
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_codeberg_uses_its_own_exact_public_origin(self):
        self.state.update(origin="https://codeberg.org", owner="berkeley")
        self.environment.update(FJTOKEN="", CBTOKEN=DUMMY_TOKEN)
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.public_calls()), 11)
        self.assertTrue(all(call["url"].startswith("https://codeberg.org/") for call in self.calls()))

    def test_secondary_forgejo_uses_its_own_token_and_public_origin(self):
        self.state.update(origin="https://git.securityops.co", owner="cristiancmoises")
        self.environment.update(FJTOKEN="", CBTOKEN="", FJTOKEN_LEGACY=DUMMY_TOKEN)
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.public_calls()), 11)
        for call in self.calls():
            self.assertTrue(call["url"].startswith("https://git.securityops.co/"))
            self.assertNotIn(DUMMY_TOKEN, " ".join(call["argv"]))
            if "/api/v1/" in call["url"]:
                self.assertIn(DUMMY_TOKEN, call["stdin"])
            else:
                self.assertEqual(call["stdin"], "")

    def test_upload_403_is_not_retried_with_disguised_metadata(self):
        name = ASSET_NAMES[1]
        (self.remote / name).unlink()
        self.state["reject_upload"] = name
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        uploads = [call for call in self.calls() if "POST" in call["argv"]]
        self.assertEqual(len(uploads), 1, "a denied write was blindly repeated")
        self.assertIn("filename=" + name, " ".join(uploads[0]["argv"]))

    def test_invalid_local_checksums_stop_before_any_transport(self):
        (self.assets / ASSET_NAMES[1]).write_bytes(b"changed local input")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), [])

    def test_identical_release_does_not_require_gnu_find_or_checksum_tools(self):
        for name in ("find", "sha256sum", "shasum"):
            tool = self.bin / name
            tool.write_text("#!" + shutil.which("sh") + "\nexit 127\n")
            tool.chmod(0o700)
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.public_calls()), 11)

    def test_checksum_manifest_must_cover_exact_payloads_once(self):
        original_lines = (self.assets / "SHA256SUMS").read_text().splitlines(keepends=True)
        extra = b"not a release asset"
        (self.workspace / "not-a-release-asset").write_bytes(extra)
        cases = {
            "missing": original_lines[1:],
            "duplicate": original_lines + original_lines[:1],
            "extra_path": original_lines + [hashlib.sha256(extra).hexdigest()
                                            + "  ../not-a-release-asset\n"],
        }
        for description, lines in cases.items():
            with self.subTest(case=description):
                manifest = "".join(lines)
                (self.assets / "SHA256SUMS").write_text(manifest)
                (self.remote / "SHA256SUMS").write_text(manifest)
                result = self.publish()
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.calls(), [])

    def test_hidden_extra_file_is_not_ignored(self):
        (self.assets / ".unexpected").write_bytes(b"must not publish")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), [])

    def test_symlink_payload_does_not_count_as_a_regular_asset(self):
        name = ASSET_NAMES[1]
        target = self.workspace / "linked-payload"
        target.write_bytes((self.assets / name).read_bytes())
        (self.assets / name).unlink()
        (self.assets / name).symlink_to(target)
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), [])

    def test_newline_filename_cannot_alias_expected_symlink_payloads(self):
        names = ASSET_NAMES[1:3]
        for name in names:
            target = self.workspace / name
            target.write_bytes((self.assets / name).read_bytes())
            (self.assets / name).unlink()
            (self.assets / name).symlink_to(target)
        # Flattening these names into newline-delimited text would disguise the
        # single unexpected regular file as two expected (symlink) payloads.
        (self.assets / "\n".join(sorted(names))).write_bytes(b"not either payload")
        result = self.publish()
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.calls(), [], "invalid file set reached publication")


if __name__ == "__main__":
    unittest.main()
