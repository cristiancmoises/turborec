import re
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import turborec


ROOT = Path(__file__).resolve().parents[1]


class ReleaseMetadataTests(unittest.TestCase):
    def test_every_packager_uses_the_source_version(self):
        version = re.escape(turborec.VERSION)
        checks = {
            "packaging/build-deb.sh": rf'PKG_VERSION="{version}"',
            "packaging/build-appimage.sh": rf'VERSION="{version}"',
            "packaging/turborec.spec": rf"(?m)^Version:\s+{version}$",
            "packaging/debian/control": rf"(?m)^Version:\s+{version}$",
            "guix.scm": rf'\(version "{version}"\)',
            "packaging/turborec.nsi": rf'!define VERSION "{version}"',
            "website/index.html": rf"Turbo Recorder {version}",
        }
        for relative, pattern in checks.items():
            with self.subTest(file=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertRegex(text, pattern)

    def test_windows_installer_bundles_pinned_python(self):
        script = (ROOT / "packaging/build-windows.sh").read_text(encoding="utf-8")
        # A pinned python.org installer with a SHA-256 verification step.
        self.assertRegex(
            script,
            r"PYTHON_URL=\"https://www\.python\.org/ftp/python/3\.12\.\d+/"
            r"python-3\.12\.\d+-amd64\.exe\"",
        )
        self.assertRegex(script, r"PYTHON_SHA256=\"[0-9a-f]{64}\"")
        self.assertIn("sha256sum -c", script)
        nsi = (ROOT / "packaging/turborec.nsi").read_text(encoding="utf-8")
        # The installer ships the bundled Python and installs it when missing.
        self.assertIn("${PYTHON_INSTALLER}", nsi)
        self.assertIn("File \"${PYTHON_INSTALLER}\"", nsi)
        self.assertIn("Function EnsurePython", nsi)
        self.assertIn("Include_tcltk=1", nsi)

    def test_release_workflow_default_matches_version(self):
        workflow = (ROOT / ".github/workflows/windows-asset.yml").read_text(
            encoding="utf-8")
        self.assertIn(f"default: v{turborec.VERSION}", workflow)

    def test_windows_setup_and_python_discovery_are_unprivileged(self):
        nsi = (ROOT / "packaging/turborec.nsi").read_text(encoding="utf-8")
        self.assertIn("RequestExecutionLevel user", nsi)
        self.assertIn('InstallDir "$LOCALAPPDATA\\Programs\\Turbo Recorder"', nsi)
        self.assertNotRegex(nsi, r"\bHKLM\b|\$PROGRAMFILES64")
        self.assertGreaterEqual(nsi.count("SetShellVarContext current"), 2)
        self.assertEqual(nsi.count('\"py\" -3 -I -c'), 2)
        self.assertIn("InstallLauncherAllUsers=0", nsi)
        self.assertIn('TargetDir="$LOCALAPPDATA\\Programs\\Python\\Python312"', nsi)
        for relative in ("packaging/turborec.cmd", "packaging/turborec-gui.cmd"):
            launcher = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("-3 -I", launcher)
            self.assertIn("%LOCALAPPDATA%\\Programs\\Python\\Python312", launcher)
            self.assertNotRegex(launcher, r"(?s)if[^\n]*\(.*exit /b %errorlevel%.*\)")

    @unittest.skipUnless(os.name == "nt", "requires the actual Windows batch launcher")
    def test_windows_batch_launcher_preserves_engine_exit_code(self):
        with tempfile.TemporaryDirectory(prefix="turborec-batch-test-") as directory:
            # Match the installed layout: launcher and engine in the same folder.
            launcher = Path(directory) / "turborec.cmd"
            shutil.copy2(ROOT / "packaging/turborec.cmd", launcher)
            shutil.copy2(ROOT / "turborec.py", Path(directory) / "turborec.py")
            environment = os.environ.copy()
            environment.pop("TURBOREC_CONFIG", None)
            environment.update(USERPROFILE=directory, HOME=directory,
                               XDG_CONFIG_HOME=str(Path(directory) / "config"))
            success = subprocess.run([str(launcher), "--version"], capture_output=True,
                                     text=True, env=environment, timeout=30)
            self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
            self.assertIn(turborec.VERSION, success.stdout)
            failure = subprocess.run([str(launcher), "--definitely-unknown-option"],
                                     capture_output=True, text=True, env=environment, timeout=30)
            self.assertEqual(failure.returncode, 2, failure.stdout + failure.stderr)

    def test_only_publication_job_has_release_write_permission(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", workflow)
        publish = workflow[workflow.index("  publish:"):]
        self.assertIn("permissions:\n      contents: write", publish)
        self.assertIn("$PSNativeCommandUseErrorActionPreference = $false", workflow)

    def test_release_includes_distribution_source_archive(self):
        name = "turborec-${VERSION}-source.zupt"
        workflow = (ROOT / ".github/workflows/release.yml").read_text(
            encoding="utf-8")
        publisher = (ROOT / "packaging/publish-release.sh").read_text(
            encoding="utf-8")
        self.assertIn("packaging/build-source-tarball.sh", workflow)
        self.assertGreaterEqual(workflow.count(name), 2)
        self.assertIn(name, publisher)
        # Windows stat exposes filesystem ACL conventions, not Git's POSIX
        # executable mode; archive-mode coverage runs in the POSIX round trips.
        if os.name == "posix":
            self.assertTrue(
                (ROOT / "packaging/build-source-tarball.sh").stat().st_mode
                & 0o111)

    def test_release_keeps_native_packages_and_zupt_distributions(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        for name in (
            "Turbo_Recorder-${VERSION}-windows-x64.exe",
            "Turbo_Recorder-${VERSION}-windows-x64-setup.exe",
            "Turbo_Recorder-${VERSION}-x86_64.AppImage",
            "turborec-${VERSION}-1.noarch.rpm",
            "turborec-${VERSION}-1.src.rpm",
            "turborec-${VERSION}-guix-x86_64.zupt",
            "turborec-${VERSION}.pkg",
            "turborec-${VERSION}-source.zupt",
            "turborec-${VERSION}.zupt",
            "turborec_${VERSION}_all.deb",
        ):
            self.assertGreaterEqual(workflow.count(name), 2, name)
        self.assertNotIn("generate_release_notes: true", workflow)
        self.assertIn("make_latest: true", workflow)

    def test_website_static_assets_exist(self):
        for relative in (
            "website/favicon.ico", "website/sitemap.xml", "website/turborec-gui.png",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_user_guides_are_packaged(self):
        for relative in ("docs/TUTORIAL.md", "docs/README.pt-BR.md"):
            self.assertTrue((ROOT / relative).is_file(), relative)
        for packager in (
            "packaging/build-deb.sh", "packaging/build-appimage.sh",
            "packaging/build-freebsd-pkg.sh", "packaging/build-tarball.sh",
            "packaging/build-rpm.sh", "packaging/turborec.spec", "guix.scm",
        ):
            text = (ROOT / packager).read_text(encoding="utf-8")
            self.assertIn("README.pt-BR.md", text, packager)


@unittest.skipUnless(
    os.name == "posix" and all(shutil.which(tool) for tool in ("git", "sh", "zupt")),
    "archive round trips require POSIX sh, git, and zupt",
)
class ReleaseArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="turborec-release-test-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        tracked = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=ROOT,
        ).decode().split("\0")
        # Newly added packaging helpers also need to be exercised before commit.
        tracked += [str(path.relative_to(ROOT)) for path in (ROOT / "packaging").glob("*.sh")]
        for relative in dict.fromkeys(filter(None, tracked)):
            source = ROOT / relative
            if not source.is_file():
                continue
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        self.run_command("git", "init", "-q")
        self.commit()

    def run_command(self, *args, expected=0, env=None):
        result = subprocess.run(
            args, cwd=self.repo, env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def commit(self):
        self.run_command("git", "add", "-A")
        self.run_command(
            "git", "-c", "user.name=Release fixture", "-c",
            "user.email=release-fixture@example.invalid", "commit", "-qm", "Fixture",
        )

    def unpack_tar(self, archive, output):
        self.run_command("zupt", "test", str(archive))
        self.run_command("zupt", "extract", "-o", str(output), str(archive))
        payloads = list(output.glob("*.tar"))
        self.assertEqual(len(payloads), 1)
        return payloads[0]

    def test_portable_archive_installs_with_executable_modes(self):
        self.run_command("sh", "packaging/build-tarball.sh")
        archive = self.repo / "dist" / f"turborec-{turborec.VERSION}.zupt"
        self.assertTrue(archive.is_file(), "portable release must be a real .zupt archive")
        output = self.repo / "unpacked"
        payload = self.unpack_tar(archive, output)
        self.assertEqual(payload.name, f"turborec-{turborec.VERSION}.tar")
        self.run_command("tar", "xf", str(payload), "-C", str(output))
        product = output / f"turborec-{turborec.VERSION}"
        for name in ("turborec", "turborecorder", "install.sh", "uninstall.sh"):
            self.assertEqual((product / name).stat().st_mode & 0o777, 0o755)
        install_env = dict(os.environ, PREFIX="/opt/turborec", DESTDIR=str(output / "installed"))
        self.run_command("sh", str(product / "install.sh"), env=install_env)
        installed = output / "installed" / "opt" / "turborec" / "bin" / "turborec"
        self.assertIn(turborec.VERSION, self.run_command(str(installed), "--version").stdout)

    def test_source_archive_excludes_private_and_untracked_content(self):
        for relative in (
            "AGENTS.md", "docs/plans/release-plan.md", "packaging/private.key",
            ".local/notes.txt", "tests/prompt.py", "docs/unnecessary.md",
        ):
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("private fixture, not distribution source\n", encoding="utf-8")
        self.commit()
        (self.repo / "untracked-prompt.txt").write_text("never ship me\n", encoding="utf-8")
        self.run_command("sh", "packaging/build-source-tarball.sh")
        archive = self.repo / "dist" / f"turborec-{turborec.VERSION}-source.zupt"
        self.assertTrue(archive.is_file(), "source release must use .zupt")
        payload = self.unpack_tar(archive, self.repo / "unpacked-source")
        self.assertEqual(payload.name, f"turborec-{turborec.VERSION}-source.tar")
        with tarfile.open(payload) as source:
            names = set(source.getnames())
            top = f"turborec-{turborec.VERSION}/"
            self.assertIn(top + "turborec.py", names)
            self.assertIn(top + "tests/test_turborec.py", names)
            self.assertIn(top + "docs/README.pt-BR.md", names)
            self.assertEqual(source.getmember(top + "packaging/build-tarball.sh").mode, 0o775)
            self.assertFalse(any("private" in name or "prompt" in name or "plans/" in name for name in names))
            self.assertNotIn(top + "AGENTS.md", names)
            self.assertNotIn(top + ".local/notes.txt", names)
            self.assertNotIn(top + "docs/unnecessary.md", names)

    def test_source_archive_payload_is_reproducible(self):
        self.run_command("sh", "packaging/build-source-tarball.sh")
        archive = self.repo / "dist" / f"turborec-{turborec.VERSION}-source.zupt"
        self.assertTrue(archive.is_file(), "source release must use .zupt")
        first = self.unpack_tar(archive, self.repo / "first").read_bytes()
        self.run_command("sh", "packaging/build-source-tarball.sh")
        second = self.unpack_tar(archive, self.repo / "second").read_bytes()
        self.assertEqual(first, second)

    def test_portable_archive_builds_from_extracted_source_without_git_metadata(self):
        self.run_command("sh", "packaging/build-source-tarball.sh")
        archive = self.repo / "dist" / f"turborec-{turborec.VERSION}-source.zupt"
        output = self.repo / "source-checkout"
        payload = self.unpack_tar(archive, output)
        self.run_command("tar", "xf", str(payload), "-C", str(output))
        source = output / f"turborec-{turborec.VERSION}"
        self.assertFalse((source / ".git").exists())
        # Keep the extracted tree outside its fixture repository so Git cannot
        # accidentally discover a parent's metadata while resolving timestamps.
        unpacked = Path(self.temporary.name) / "standalone-source"
        source.rename(unpacked)
        env = dict(os.environ)
        env.pop("SOURCE_DATE_EPOCH", None)
        tools = Path(self.temporary.name) / "tools-without-git"
        tools.mkdir()
        for tool in (
            "sh", "cat", "cp", "chmod", "mkdir", "dirname", "basename", "sed", "head",
            "mktemp", "rm", "tar", "grep", "date", "zupt", "cmp", "mv", "python3",
        ):
            (tools / tool).symlink_to(shutil.which(tool))
        for tool_path in (env["PATH"], str(tools)):
            with self.subTest(path_has_git=tool_path != str(tools)):
                result = subprocess.run(
                    ["sh", "packaging/build-tarball.sh"], cwd=unpacked,
                    env=dict(env, PATH=tool_path), text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        portable = unpacked / "dist" / f"turborec-{turborec.VERSION}.zupt"
        self.assertTrue(portable.is_file())
        rebuilt_tar = self.unpack_tar(portable, self.repo / "rebuilt-portable")
        with tarfile.open(rebuilt_tar) as rebuilt:
            engine = rebuilt.getmember(f"turborec-{turborec.VERSION}/turborec")
            self.assertEqual(engine.mode, 0o755)
            self.assertIn(turborec.VERSION.encode(), rebuilt.extractfile(engine).read())

    def test_source_archive_refuses_uncommitted_tracked_edits(self):
        with (self.repo / "turborec.py").open("a", encoding="utf-8") as source:
            source.write("\n# uncommitted fixture\n")
        result = subprocess.run(
            ["sh", "packaging/build-source-tarball.sh"], cwd=self.repo,
            text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked working-tree changes", result.stderr)
        self.assertFalse((self.repo / "dist").exists())

    def test_bootstrap_version_validation_accepts_real_zupt_output(self):
        # Exercise the actual version-boundary command without fetching and
        # compiling the entire dependency during every unit-test run.
        bootstrap = (self.repo / "packaging/install-zupt.sh").read_text(encoding="utf-8")
        check = next(line for line in bootstrap.splitlines() if '"${SOURCE}/zupt" version' in line)
        source = self.repo / "bootstrap-source"
        source.mkdir()
        (source / "zupt").symlink_to(shutil.which("zupt"))
        env = dict(os.environ, SOURCE=str(source), ZUPT_VERSION="5.2.9")
        self.assertEqual(
            self.run_command("sh", "-c", check, env=env).stdout.strip(),
            "zupt 5.2.9 (ZUPT)",
        )
        env["ZUPT_VERSION"] = "0.0.0"
        self.run_command("sh", "-c", check, env=env, expected=1)

    def test_bootstrap_rejects_corrupt_download_before_compilation(self):
        tools = self.repo / "fake-network"
        tools.mkdir()
        # Only the external download and expensive compilation are substituted;
        # the real checksum implementation and installer control flow run.
        downloader = tools / "curl"
        downloader.write_text(
            '#!/bin/sh\nwhile [ "$#" -gt 0 ]; do\n'
            '  if [ "$1" = "-o" ]; then shift; printf "corrupt source" > "$1"; exit 0; fi\n'
            '  shift\ndone\nexit 1\n', encoding="utf-8",
        )
        compiler = tools / "make"
        compiler.write_text('#!/bin/sh\ntouch "$COMPILE_MARKER"\nexit 1\n', encoding="utf-8")
        downloader.chmod(0o755)
        compiler.chmod(0o755)
        marker = self.repo / "compiled"
        env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ["PATH"],
                   COMPILE_MARKER=str(marker))
        result = subprocess.run(
            ["sh", "packaging/install-zupt.sh", str(self.repo / "installed-bin")],
            cwd=self.repo, env=env, text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", result.stdout + result.stderr)
        self.assertFalse(marker.exists(), "unverified source must never be compiled")
        self.assertFalse((self.repo / "installed-bin").exists())

    def test_invalid_thread_count_preserves_existing_release_archive(self):
        payload = self.repo / "payload.tar"
        with tarfile.open(payload, "w") as archive:
            archive.add(self.repo / "LICENSE", arcname="LICENSE")
        output = self.repo / "existing.zupt"
        output.write_bytes(b"previous verified release")
        for value in ("0", "65", "oops", "999999999999999999999999999999999"):
            with self.subTest(threads=value):
                result = subprocess.run(
                    ["sh", "packaging/build-zupt-archive.sh", str(payload), str(output)],
                    cwd=self.repo, env=dict(os.environ, ZUPT_THREADS=value),
                    text=True, capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ZUPT_THREADS must be 1-64", result.stderr)
                self.assertEqual(output.read_bytes(), b"previous verified release")

    @unittest.skipIf(getattr(os, "geteuid", lambda: 0)() == 0, "root bypasses directory permissions")
    def test_archive_can_publish_below_search_only_ancestor(self):
        payload = self.repo / "payload.tar"
        with tarfile.open(payload, "w") as archive:
            archive.add(self.repo / "LICENSE", arcname="LICENSE")
        restricted = Path(self.temporary.name) / "search-only"
        output_dir = restricted / "release-assets"
        output_dir.mkdir(parents=True)
        scratch = Path(self.temporary.name) / "private-tmp"
        scratch.mkdir(mode=0o700)
        restricted.chmod(0o111)
        self.addCleanup(restricted.chmod, 0o700)
        self.assertFalse(os.access(restricted, os.R_OK))
        output = output_dir / "release.zupt"
        self.run_command(
            "sh", "packaging/build-zupt-archive.sh", str(payload), str(output),
            env=dict(os.environ, TMPDIR=str(scratch)),
        )
        # Read/copy through the searchable ancestor, but ask ZUPT to open only
        # fully readable temporary ancestors when validating the published copy.
        readable_archive = self.repo / "published.zupt"
        shutil.copy2(output, readable_archive)
        restored = self.unpack_tar(readable_archive, self.repo / "published-extracted")
        self.assertEqual(restored.read_bytes(), payload.read_bytes())
        self.assertEqual(list(scratch.iterdir()), [])
        self.assertEqual(list(output_dir.glob(".zupt-build.*")), [])

    def test_failed_validation_preserves_existing_archive_and_cleans_staging(self):
        payload = self.repo / "payload.tar"
        with tarfile.open(payload, "w") as archive:
            archive.add(self.repo / "LICENSE", arcname="LICENSE")
        output_dir = self.repo / "output"
        output_dir.mkdir()
        output = output_dir / "release.zupt"
        output.write_bytes(b"previous verified archive")
        scratch = self.repo / "private-tmp"
        scratch.mkdir(mode=0o700)
        tools = self.repo / "failure-tools"
        tools.mkdir()
        checker = tools / "zupt"
        checker.write_text(
            '#!/bin/sh\nif [ "$1" = test ]; then\n'
            '  printf "injected verification failure\\n" >&2\n  exit 1\nfi\n'
            'exec "$REAL_ZUPT" "$@"\n', encoding="utf-8",
        )
        checker.chmod(0o755)
        result = self.run_command(
            "sh", "packaging/build-zupt-archive.sh", str(payload), str(output), expected=1,
            env=dict(os.environ, TMPDIR=str(scratch), REAL_ZUPT=shutil.which("zupt"),
                     PATH=str(tools) + os.pathsep + os.environ["PATH"]),
        )
        self.assertIn("injected verification failure", result.stderr)
        self.assertEqual(output.read_bytes(), b"previous verified archive")
        self.assertEqual(list(scratch.iterdir()), [])
        self.assertEqual(list(output_dir.iterdir()), [output])


if __name__ == "__main__":
    unittest.main()
