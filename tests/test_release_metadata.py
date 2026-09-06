import re
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

    def test_release_includes_distribution_source_archive(self):
        name = f"turborec-${{VERSION}}-source.tar.gz"
        workflow = (ROOT / ".github/workflows/release.yml").read_text(
            encoding="utf-8")
        publisher = (ROOT / "packaging/publish-release.sh").read_text(
            encoding="utf-8")
        self.assertIn("packaging/build-source-tarball.sh", workflow)
        self.assertGreaterEqual(workflow.count(name), 2)
        self.assertIn(name, publisher)
        self.assertTrue(
            (ROOT / "packaging/build-source-tarball.sh").stat().st_mode
            & 0o111)

    def test_website_static_assets_exist(self):
        for relative in (
            "website/favicon.ico",
            "website/sitemap.xml",
            "website/turborec-gui.png",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_user_guides_are_packaged(self):
        for relative in ("docs/TUTORIAL.md", "docs/README.pt-BR.md"):
            self.assertTrue((ROOT / relative).is_file(), relative)
        for packager in (
            "packaging/build-deb.sh",
            "packaging/build-appimage.sh",
            "packaging/build-freebsd-pkg.sh",
            "packaging/build-tarball.sh",
            "packaging/build-rpm.sh",
            "packaging/turborec.spec",
            "guix.scm",
        ):
            text = (ROOT / packager).read_text(encoding="utf-8")
            self.assertIn("README.pt-BR.md", text, packager)


if __name__ == "__main__":
    unittest.main()
