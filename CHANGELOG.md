# Changelog

All notable changes to Turbo Recorder are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.0] — 2026-06-13

### Fixed
- **Slow / "≈2× slow-motion" recordings.** Live screen capture must encode in
  real time or frames pile up and the video plays back slowed and choppy. The
  old NVENC `p7` (+ lookahead) and software `slow`/`film` presets fell far below
  real-time at high resolution/fps. Encoders now use real-time-capable presets
  (NVENC `p4`–`p6`, QSV medium/fast, VAAPI cqp, AMF balanced/speed, VideoToolbox
  `realtime=1`, x264/x265 `veryfast`/`ultrafast`) **and** the output is forced to
  constant frame rate (`-fps_mode cfr -r FPS`), so playback speed is always
  correct. A 6 s capture now yields exactly 6.000 s / 60 fps / 360 frames.
- **GUI timer frozen at `00:00:00`.** A dangling reference to the removed
  software-encoding switch raised a `NameError` in `do_start()` just before the
  elapsed-timer tick was scheduled, so the clock and REC pulse never started.

### Added
- **Encoder backend selection** — `--backend auto|gpu|cpu` (with `--gpu` / `--cpu`
  shorthands) on the CLI, and an **Encoder: Auto / GPU / CPU** control in the GUI.
- **OBS-style capture targets** — the new `targets` subcommand lists the full
  screen, each monitor and capturable windows; `--monitor NAME`, `--window TITLE`
  and `--region WxH+X+Y` select what to grab. The GUI gains a **Source** picker
  with a refresh button. Screen capture now supports an X/Y offset.

## [2.1.0] — 2026-06-13

### Added
- **Redesigned dark GUI** (near-black background, cyan accents): segmented capture
  mode selector, hardware status header, mic/system pickers with presence dots,
  live FFmpeg command preview, output folder + live filename preview, and a footer
  with a prominent Start/Stop, live elapsed timer, pulsing REC indicator and
  running output-file size.
- **Packaging**: `.deb`, `.rpm` and AppImage build scripts under `packaging/`
  (the `.deb` builds with `dpkg-deb`, or portably with `ar`/`tar`/`xz`), a desktop
  entry, a scalable cyan-on-black icon, and a GitHub Actions release workflow that
  builds and publishes all three formats on `v*` tags.
- **CLI**: `devices` and `encoders` subcommands; `detect --json`; `-t/--duration`
  (accepts `90`, `5m`, `1m30s`, `2h`, `HH:MM:SS`); `--countdown`; `--open`;
  `--version`; and JSON config via `--config`, `$TURBOREC_CONFIG` or
  `~/.config/turborec/config.json`.

### Fixed
- GUI startup crash from a custom `Vert.TScrollbar` ttk style with no layout.

## [2.0.0] — 2026-06-13

### Added
- **Cross-platform `turborec.py`** (Linux/macOS/Windows, Python stdlib + FFmpeg):
  auto-detects OS, display server, CPU vendor (Intel/AMD/Apple), GPU and the best
  hardware encoder (NVENC/QSV/VAAPI/AMF/VideoToolbox, software fallback), screen
  resolution, microphone and system-audio sources. Ships an argparse CLI and a
  Tkinter GUI.
- Quality-first presets, BT.709 color metadata, lossless FLAC audio (AAC/Opus
  optional) with soxr resampling.

### Changed
- **`turborecorder`** (Linux/X11 bash) upgraded: auto-detects CPU/GPU vendor and
  the best encoder (NVENC > VAAPI > software), auto-detects default mic + system
  audio (no more hardcoded device names), full-screen capture by default, and adds
  HEVC / codec / quality / audio-codec options.

[2.2.0]: https://github.com/cristiancmoises/turborec/releases/tag/v2.2.0
[2.1.0]: https://github.com/cristiancmoises/turborec/releases/tag/v2.1.0
[2.0.0]: https://github.com/cristiancmoises/turborec/releases/tag/v2.0.0
