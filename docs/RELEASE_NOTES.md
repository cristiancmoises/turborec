# Release Notes - Turbo Recorder v3.7.0

**Release Date:** 2026-07-24  
**Version:** 3.7.0  
**Type:** Major release with 4K defaults and quality enhancements

## Summary

Turbo Recorder v3.7.0 introduces 4K resolution as the default output, cinematic 23.976 fps frame rate, and lossless FLAC audio as the standard configuration. All encoder backends have been optimized for 4K quality with reduced CRF/qp thresholds.

## New Features

### 4K Default Resolution
- **3840×2160** is now the default resolution for maximum quality
- Ideal for YouTube's 4K tier and high-quality streaming platforms
- Resolution can still be scaled down to 720p/1080p/1440p for bandwidth constraints

### Cinematic Frame Rate
- **23.976 fps** default for cinematic playback
- Superior quality for film-like content
- Higher fps modes still available via CLI for sports/gaming

### Lossless Audio
- **FLAC** remains the default audio codec
- Full 48kHz stereo audio preserved
- Lossless compression with excellent quality

## Quality Improvements

### Encoder Optimizations
- **NVENC:** CRF values [16, 19, 22, 25] for 4K
- **QSV:** Global quality [18, 21, 24, 28] for 4K
- **libx264:** CRF [16, 18, 21, 24] for 4K
- **libx265:** CRF [16, 18, 21, 24] for 4K
- **libsvtav1:** qp [16, 18, 21, 24] for 4K
- **libaom-av1:** qp [16, 18, 21, 24] for 4K

### Bitrate Recommendations
- **4K live streaming:** 40 Mbps base bitrate
- Matches YouTube's premium quality recommendations
- Reduces compression artifacts at high resolution

### Recording Mode
- Defaults to **auto** mode
- Captures screen + mic + system audio when all sources exist
- Falls back to available sources (screen + mic, screen + system, or video-only)
- Makes first-run recording work on ordinary installations

## Platform Improvements

### Windows
- Extended loopback recognition with localized names (e.g., Brazilian Portuguese "Mixagem estéreo")
- GUI allows explicit system-audio selection from every DirectShow source
- Unicode device names now usable with UTF-8 decoding
- Faster enumeration with timeouts for slow DirectShow drivers
- Improved multi-monitor and window capture with signed geometry

### macOS
- Correct AVFoundation display index for screen capture
- Multiple displays appear in source picker
- Explicit regions cropped from selected display
- Invalid regions fail closed

### Linux/Wayland
- PipeWire combined source for A/V sync (null sink + two loopbacks)
- Graceful fallback to two-process capture if combined source unavailable
- Older PulseAudio support via `pactl info`
- No orphaned processes or leaked temp files

## Documentation Updates

- Added complete Brazilian Portuguese guide: [`docs/README.pt-BR.md`](docs/README.pt-BR.md)
- Enhanced regression coverage for all platform-specific features
- Updated installation and usage documentation

## Installation

### Debian/Ubuntu
```bash
sudo dpkg -i turborec_3.7.0_all.deb
# Or from tarball:
sudo tar -xzf turborec-3.7.0.tar.gz
sudo ./turborec-3.7.0/install.sh
```

### Portable
```bash
tar -xzf turborec-3.7.0.tar.gz
./turborec-3.7.0/turborec
```

## Package Availability

| Format | Status | Size |
|--------|--------|------|
| Debian (.deb) | ✅ Available | 100KB |
| Portable tarball | ✅ Available | 109KB |
| AppImage | ❌ Requires tooling | - |
| RPM | ❌ Requires tooling | - |
| Windows installer | ❌ Requires tooling | - |
| macOS DMG | ❌ Requires tooling | - |

## Technical Details

See [`CHANGELOG.md`](CHANGELOG.md) for the complete changelog.

## License

See [`LICENSE`](LICENSE) for the full license text.

## Support

For issues, feature requests, or questions, please visit the project repository.
