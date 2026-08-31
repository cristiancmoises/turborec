# Release Notes - Turbo Recorder v3.8.0

**Release Date:** 2026-08-31  
**Version:** 3.8.0  
**Type:** Minor release — self-contained Windows installer

## Summary

Turbo Recorder v3.8.0 makes the classic Windows installer (`setup.exe`) fully
self-contained: it now **bundles Python 3.12 (with Tk)**, FFmpeg and the app,
so the target machine needs nothing pre-installed — the same guarantee the
zero-install `.exe` already offered.

## What's New

### Self-contained Windows installer
- `Turbo_Recorder-<version>-windows-x64-setup.exe` now bundles the pinned
  python.org **Python 3.12.10 installer** (SHA-256 verified, matches the MD5
  published on python.org) plus the pinned FFmpeg 8.1.2 build.
- During install, Python is installed **silently, per-user** (with Tk, pip,
  the `py` launcher and PATH prepended) **only if** no Python 3.8+ with Tk is
  already detected — existing installations are never touched.
- The installer still creates Start-Menu/Desktop shortcuts and an
  Add/Remove Programs entry; the uninstaller removes the app but **never**
  uninstalls the shared Python.
- Installer size grows to ~101 MB (was ~75 MB) to carry Python.

### Quality / maintenance
- Fixed the shellcheck SC2015 lint finding in `build-windows.sh`.
- Packaging metadata and all user guides updated to v3.8.0; the Windows docs
  now describe both the portable `.exe` and the self-contained installer.

## Installation

### Windows — installer (self-contained, no prerequisites)
```cmd
Turbo_Recorder-3.8.0-windows-x64-setup.exe
```

### Windows — zero-install portable app (unchanged)
```powershell
Turbo_Recorder-3.8.0-windows-x64.exe gui
```

### Debian/Ubuntu
```bash
sudo dpkg -i turborec_3.8.0_all.deb
```

### RPM (Fedora/RHEL/openSUSE)
```bash
sudo dnf install ./turborec-3.8.0-1.noarch.rpm
```

### AppImage
```bash
chmod +x Turbo_Recorder-3.8.0-x86_64.AppImage
./Turbo_Recorder-3.8.0-x86_64.AppImage
```

### Portable tarball
```bash
tar -xzf turborec-3.8.0.tar.gz && cd turborec-3.8.0
./turborec --help
```

### GNU Guix pack (any GNU/Linux)
```bash
tar -xzf turborec-3.8.0-guix-x86_64.tar.gz
./bin/turborec --help
```

## Package Availability

| Format | Status | Size |
|--------|--------|------|
| Debian (.deb) | ✅ Available | ~100KB |
| Portable tarball | ✅ Available | ~110KB |
| AppImage | ✅ Available | ~1MB |
| RPM (+ source RPM) | ✅ Available | ~135KB + ~117KB |
| Windows installer (NSIS, Python bundled) | ✅ Available | ~101MB |
| GNU Guix relocatable pack | ✅ Available | ~480MB |
| Windows zero-install .exe | ✅ Available | ~85MB |
| FreeBSD .pkg | ✅ Available | ~100KB |
| macOS DMG | ➖ Not part of release asset set | - |

## Technical Details

See [`CHANGELOG.md`](CHANGELOG.md) for the complete changelog.

## License

See [`LICENSE`](LICENSE) for the full license text.

## Support

For issues, feature requests, or questions, please visit the project repository.
