# Release Notes - Turbo Recorder v3.7.1

**Release Date:** 2026-08-31  
**Version:** 3.7.1  
**Type:** Patch release — timed-recording fix

## Summary

Turbo Recorder v3.7.1 fixes the `--duration` parser: `1h30` is now read as
the natural shorthand for **1 hour 30 minutes**, instead of the previous
1 hour + 30 seconds. All other duration forms are unchanged.

## What's Fixed

### `--duration` hour-minute shorthand
- `turborec record -t 1h30` now records for **90 minutes** (was 1 h 30 s).
- `2h15` → 2 h 15 min; `1h30m`, `1h30m45s`, `1h30s` keep their exact meanings.
- Bare trailing numbers still mean seconds: `90`, `1m30`, `1h30s`.
- Clock format (`HH:MM:SS`, `MM:SS`) and the documented forms `90s`, `5m`,
  `1h30m` are byte-for-byte unchanged; invalid input is still rejected.

## Also in this release

- The Forgejo mirror moved to its live instance:
  [`git.securityops.com.br/cristiancmoises/turborec`](https://git.securityops.com.br/cristiancmoises/turborec)
  (the former `git.securityops.co` account requires a password change and no
  longer accepts API authentication).
- Documentation and package metadata updated to v3.7.1 (README, guides,
  DEB/RPM/Guix/AppImage/NSIS packaging, release workflow defaults).
- Added regression tests covering every `--duration` form.

## Installation

### Debian/Ubuntu
```bash
sudo dpkg -i turborec_3.7.1_all.deb
```

### RPM (Fedora/RHEL/openSUSE)
```bash
sudo dnf install ./turborec-3.7.1-1.noarch.rpm
```

### AppImage
```bash
chmod +x Turbo_Recorder-3.7.1-x86_64.AppImage
./Turbo_Recorder-3.7.1-x86_64.AppImage
```

### Portable tarball
```bash
tar -xzf turborec-3.7.1.tar.gz && cd turborec-3.7.1
./turborec --help
```

### Windows (NSIS installer)
```cmd
Turbo_Recorder-3.7.1-windows-x64-setup.exe
```

### GNU Guix pack (any GNU/Linux)
```bash
tar -xzf turborec-3.7.1-guix-x86_64.tar.gz
./bin/turborec --help
```

## Package Availability

| Format | Status | Size |
|--------|--------|------|
| Debian (.deb) | ✅ Available | ~100KB |
| Portable tarball | ✅ Available | ~110KB |
| AppImage | ✅ Available | ~1MB |
| RPM (+ source RPM) | ✅ Available | ~135KB + ~117KB |
| Windows installer (NSIS) | ✅ Available | ~75MB |
| GNU Guix relocatable pack | ✅ Available | ~480MB |
| Windows zero-install .exe | ⏳ GitHub Actions (on tag push) | - |
| FreeBSD .pkg | ⏳ GitHub Actions (VM) | - |
| macOS DMG | ➖ Not part of release asset set | - |

## Technical Details

See [`CHANGELOG.md`](CHANGELOG.md) for the complete changelog.

## License

See [`LICENSE`](LICENSE) for the full license text.

## Support

For issues, feature requests, or questions, please visit the project repository.
