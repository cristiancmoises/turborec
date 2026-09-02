# Release Notes - Turbo Recorder v3.8.1

**Release Date:** 2026-08-31  
**Version:** 3.8.1  
**Type:** Patch release — data-loss fix and release-pipeline hardening

## Summary

Turbo Recorder v3.8.1 fixes a silent data-loss edge case (two recordings
started in the same second could overwrite each other) and hardens the
release pipeline against the stale-mirror failure observed after v3.8.0.

## What's Fixed

### Same-second recordings never overwrite each other
- The output timestamp is second-granularity and `ffmpeg` runs with `-y`, so
  starting a second recording within the same second as the previous one
  silently replaced the first file.
- Output paths are now collision-safe: `…_2026-08-31_14-20-33.mkv` becomes
  `…_2026-08-31_14-20-33_1.mkv`, `_2.mkv`, … when the name is already taken
  (FFmpeg and Wayland/wf-recorder paths both fixed).

### Release pipeline hardening (stale-mirror defense)
- After v3.8.0, a stale force-mirror (the retired `git.securityops.co`
  instance) deleted the v3.7.1/v3.8.0 tags and reverted `main` on GitHub —
  and Codeberg's pull-mirror followed. The refs were restored via the API.
- `packaging/publish-release.sh` now **verifies each forge's git tag ref
  against the local tag** before creating or reusing a release and refuses
  to publish on a missing/mismatched ref, so a wiped tag can no longer anchor
  a release on an old commit silently.
- **Action needed from the repo owner:** disable or refresh the
  `git.securityops.co` push-mirror (its account is password-locked, so it
  cannot be fixed via API). Until then the drift may recur — the preflight
  makes it loud instead of silent.

### CI modernization
- GitHub Actions moved off the deprecated Node-20 runtimes:
  `actions/checkout@v4` → `@v6`, `actions/upload-artifact@v4` → `@v5`,
  `actions/download-artifact@v4` → `@v5` (upload and download move together
  because the v4/v5 artifact formats are incompatible).

## Installation

All packages are unchanged in layout; see the v3.8.0 notes for the
self-contained Windows installer (Python 3.12 bundled).

```bash
# Debian/Ubuntu
sudo dpkg -i turborec_3.8.1_all.deb
# RPM
sudo dnf install ./turborec-3.8.1-1.noarch.rpm
# AppImage
chmod +x Turbo_Recorder-3.8.1-x86_64.AppImage && ./Turbo_Recorder-3.8.1-x86_64.AppImage
# Windows
Turbo_Recorder-3.8.1-windows-x64-setup.exe   # or the portable .exe
```

## Package Availability

| Format | Status |
|--------|--------|
| Debian (.deb) / RPM (+ source RPM) | ✅ |
| AppImage / portable tarball | ✅ |
| Windows installer (Python bundled) / zero-install .exe | ✅ |
| GNU Guix relocatable pack / FreeBSD .pkg | ✅ |
| macOS DMG | ➖ Not part of release asset set |

## Technical Details

See [`CHANGELOG.md`](CHANGELOG.md) for the complete changelog.

## License

See [`LICENSE`](LICENSE) for the full license text.

## Support

For issues, feature requests, or questions, please visit the project repository.
