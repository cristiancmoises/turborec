# Changelog

All notable changes to Turbo Recorder are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.4.0] — 2026-07-13

### Added
- **Zero-install, self-contained Windows app.** The Windows `.exe` now bundles
  **FFmpeg** (plus Python and Tk) inside it, so users just download and run —
  no Python, no separate FFmpeg, no `PATH` setup, no admin install. When frozen,
  Turbo Recorder finds its bundled `ffmpeg.exe` automatically (a system FFmpeg on
  `PATH`, or `--ffmpeg`, still overrides it). The bundling is wired into both the
  release workflow and the on-demand `windows-asset` workflow.

### Changed
- Turbo Recorder is now developed **primary on Forgejo**
  (`git.securityops.co/cristiancmoises/turborec`), with **GitHub** and
  **Codeberg** as push-mirrors. Releases (with all binaries) are published on
  Forgejo as well as GitHub.

### Security
Full adversarial security audit of the codebase and CI/release supply chain, with
all confirmed findings fixed:
- **Windows PATH hardening.** The self-contained build now exposes **only** the
  bundle's own extracted directory (`sys._MEIPASS`) on `PATH`, and only if it
  actually contains the bundled `ffmpeg` — never the folder the portable `.exe`
  was launched from (e.g. Downloads). This closes a binary-planting vector where a
  co-located `nvidia-smi.exe` could have been executed.
- **Stream key no longer leaks via ffmpeg stderr.** ffmpeg prints the output RTMP
  URL (which contains the key) at info/error level; that child stderr is now piped
  through the same redaction as everything else, so the key never reaches the
  terminal, scrollback, or a redirected log.
- **Supply-chain pinning.** The bundled FFmpeg is a pinned, immutable gyan.dev
  build verified by SHA-256 in CI; PyInstaller and appimagetool are likewise
  pinned (appimagetool moved off the rolling `continuous` tag to a checksummed
  versioned release).
- **Filesystem hardening.** Wayland mux scratch files moved from the user-chosen
  output directory into a private `0700` temp dir (removing a symlink-overwrite
  vector on shared output dirs), and the config loader now tolerates pathologically
  deep JSON instead of crashing.

## [3.3.0] — 2026-07-13

### Added
- **YouTube live streaming (OBS-style)** — go live straight from Turbo Recorder
  with your YouTube **stream key**, no third-party software. CLI: `--stream KEY`
  (optionally `--stream-url` for a custom RTMP/RTMPS ingest; defaults to YouTube's
  `rtmps://a.rtmps.youtube.com:443/live2`); GUI: a masked **Stream key** field.
  The engine forces a streaming-correct pipeline — H.264 (CBR at YouTube's
  recommended bitrate for the frame size), AAC audio, a 2-second keyframe interval
  (GOP = 2×fps) and FLV — while still mixing mic + system audio. On Wayland,
  `wf-recorder` encodes into an mpegts FIFO that ffmpeg stream-copies and pushes,
  so live streaming works on wlroots compositors too. Video-only streams get a
  silent audio track so YouTube always sees audio.
- **Adaptive, resolution-aware encoder tuning** — the encoder presets now scale
  with the actual pixel throughput (megapixels/sec). At 1080p there is spare
  encode time, so Turbo Recorder uses much slower/higher-quality presets
  (NVENC `p7` + temporal-AQ + look-ahead, x264 `slow` CRF 17, x265, SVT-AV1),
  and it steps down toward faster presets only at 4K / high-fps to keep capture
  real-time. Result: visibly better quality at the resolutions most people record,
  with no dropped frames at the demanding ones.

### Security
- **Stream keys are treated as credentials.** They are redacted (`••••`) from every
  printed command, the `--dry-run` output, the GUI command preview, and the
  end-of-stream status line — including whitespace-padded keys. The live preview /
  dry-run no longer creates a temporary stream pipe on disk. A note is shown when
  going live that, as with any ffmpeg RTMP push, the key is visible to other local
  users via the process list on a shared machine. `--stream-url` is restricted to
  `rtmp://` / `rtmps://` ingests.

### Packaging
- **BSD / portable binary release.** A new architecture-independent tarball
  (`turborec-<version>.tar.gz`, with `install.sh` / `uninstall.sh`) installs on any
  Unix with Python 3 — FreeBSD, OpenBSD, NetBSD, DragonFly, illumos, Linux, macOS —
  and a native **FreeBSD package** (`turborec-<version>.pkg`, `pkg add`) is now
  built and smoke-tested in CI alongside the `.deb`, `.rpm`, and AppImage.

## [3.2.0] — 2026-07-12

### Added
- **Selectable output resolution (`-R/--resolution`)** — `native` (default),
  `720p`, `1080p`, `1440p`, `4k`. The recording is scaled with high-quality
  lanczos (aspect preserved, padded to the exact standard frame), so you can
  **record true 4K videos** even from a 1080p/1200p screen. This matters for
  YouTube: it picks its quality tier (and bitrate budget) from the uploaded
  resolution — a native 1920×1200 capture can land at a low tier, while a 4K
  upload gets the high-bitrate 4K pipeline. Works on every backend: ffmpeg
  (X11/macOS/Windows; scaling runs before any NVENC/VAAPI/QSV hwupload) and
  Wayland (`wf-recorder -F`). Available in the CLI, the GUI (**Output** dropdown),
  and the JSON config (`"resolution": "4k"`).

### Notes
- On Wayland, choosing a scaled resolution with a VAAPI encoder falls back to the
  software encoder (the software scale chain can't feed VAAPI hardware frames).

## [3.1.0] — 2026-07-08

### Added
- **Audio channel handling (`--audio-channels`)** — fixes recordings that only
  play on one side. `left`/`right` clone that channel to **both** outputs at full
  level (ideal for a mono mic wired to one input, e.g. a Focusrite where only one
  channel is live); `mono` averages both channels (clip-safe); `stereo` (default)
  keeps the source. Applies to every audio path — the ffmpeg backend (X11/macOS/
  Windows, audio-only modes) and Wayland (a non-`stereo` choice routes audio
  through ffmpeg + mux so the channel remap always applies). Available in the CLI
  and as a **Channels** dropdown in the GUI.
- **23 fps** added to the GUI frame-rate presets — a great quality/CPU sweet spot
  (~2.6× less encoding work than 60 fps), which meaningfully lowers CPU load
  during software (Wayland/CPU) capture. Any FPS is still settable via `-f`.

## [3.0.0] — 2026-06-28

### Added
- **Wayland (wlroots) screen capture** via `wf-recorder` — sway, Hyprland, river,
  etc. `x11grab` only ever saw XWayland, so on a Wayland session video was
  black/empty; turborec now auto-detects Wayland and records the real desktop.
  Per-output (`--monitor`), region (`--region`, mapped to the right output), and
  sway **window** capture are supported; outputs/windows are read from
  `swaymsg`/`wlr-randr`.
- **Perfectly A/V-synced mic+system on Wayland.** For `video_both`, turborec
  creates a temporary PipeWire combined source (null sink + two loopbacks) so a
  single `wf-recorder` process captures video and mixed audio under one clock —
  no lip-sync drift — then tears the modules down. Falls back to a two-process
  capture + mux if the combined source can't be created. The chosen audio codec
  (FLAC/AAC/Opus) is honored via `wf-recorder -C`.

### Fixed (from an adversarial security + performance review)
- **AV1 software no longer uses the non-real-time `libaom-av1`** for live capture:
  prefers `libsvtav1` (real-time presets), else falls back to `libx264` — matching
  behavior across the ffmpeg and Wayland paths.
- **No orphaned processes / leaked temp files** when the capture crashes: the GUI
  and CLI now tear down every process, unload PipeWire modules, and clean up.
- Processes are reaped after kill/terminate (no zombies); a `None` exit code is
  treated as failure, not success.
- wf-recorder is always given a valid `-o <output>` (no interactive prompt hang);
  duration timing uses a monotonic deadline; region is clamped to the output;
  `--region WxH` (offset-less) is accepted on Wayland; the `wlr-randr` fallback
  reads each output's `Position:`.
- Window/output titles from `swaymsg` are sanitized before display (no terminal
  escape-sequence injection). Preview no longer emits encoder warnings to stderr.

### Notes
- On NVIDIA + Wayland, `wf-recorder` encodes in software (`libx264`/`libx265`);
  NVENC is not reachable through it. At 1080p/1200p this is comfortably real-time.
- Requires **`wf-recorder`** on Wayland (`guix install wf-recorder` ·
  `sudo apt install wf-recorder` · `sudo dnf install wf-recorder`).

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

[3.3.0]: https://github.com/cristiancmoises/turborec/releases/tag/v3.3.0
[3.2.0]: https://github.com/cristiancmoises/turborec/releases/tag/v3.2.0
[3.1.0]: https://github.com/cristiancmoises/turborec/releases/tag/v3.1.0
[3.0.0]: https://github.com/cristiancmoises/turborec/releases/tag/v3.0.0
[2.2.0]: https://github.com/cristiancmoises/turborec/releases/tag/v2.2.0
[2.1.0]: https://github.com/cristiancmoises/turborec/releases/tag/v2.1.0
[2.0.0]: https://github.com/cristiancmoises/turborec/releases/tag/v2.0.0
