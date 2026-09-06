# Turbo Recorder — Complete User Guide

> Record your screen and audio at the **best quality your hardware can deliver** —
> on Linux, macOS, Windows, FreeBSD, OpenBSD, NetBSD or DragonFly. Turbo Recorder
> probes your machine and configures everything (OS, GPU, encoder, screen, mic,
> system audio) automatically, then builds a real-time, correct-speed FFmpeg
> pipeline. Use the **GUI** or the **CLI**.

---

## Table of contents

1. [Install](#1-install)
2. [60-second quick start](#2-60-second-quick-start)
3. [Core concepts](#3-core-concepts)
4. [Using the GUI](#4-using-the-gui)
5. [Using the CLI](#5-using-the-cli)
6. [Capture modes](#6-capture-modes)
7. [Choosing what to capture (screen, monitor, window, region)](#7-choosing-what-to-capture)
8. [Choosing how to encode (CPU vs GPU, quality, codec)](#8-choosing-how-to-encode)
9. [Audio](#9-audio)
10. [Live streaming to YouTube (OBS-style)](#10-live-streaming-to-youtube)
11. [Timed recording, countdown and auto-open](#11-timed-recording-countdown-and-auto-open)
12. [Saving your defaults (config file)](#12-saving-your-defaults)
13. [The Linux bash recorder (`turborecorder`)](#13-the-linux-bash-recorder)
14. [Recipes and cookbook](#14-recipes-and-cookbook)
15. [Tips for the best possible quality](#15-tips-for-the-best-possible-quality)
16. [Troubleshooting](#16-troubleshooting)
17. [FAQ](#17-faq)

---

## 1. Install

**Requirements:** [FFmpeg](https://ffmpeg.org/download.html) on your `PATH`,
Python 3.8+, and (for the GUI) Tk — bundled with the python.org installers on
macOS/Windows; a separate package on Linux. On a **Linux Wayland** session (sway,
Hyprland, river, …) screen capture additionally needs
[`wf-recorder`](https://github.com/ammen99/wf-recorder)
(`sudo apt install wf-recorder` · `sudo dnf install wf-recorder` ·
`guix install wf-recorder`).

### Linux — packages

```bash
# Debian / Ubuntu
sudo apt install ./turborec_3.9.1_all.deb        # pulls ffmpeg, python3, python3-tk

# Fedora / RHEL / openSUSE
sudo dnf install ./turborec-3.9.1-1.noarch.rpm   # accepts any RPM provider of /usr/bin/ffmpeg

# Any Linux — portable AppImage (uses your host ffmpeg/python/tk)
chmod +x Turbo_Recorder-3.9.1-x86_64.AppImage
./Turbo_Recorder-3.9.1-x86_64.AppImage
```

Get these from the project **Releases** page, or build them yourself with the
scripts in [`packaging/`](../packaging/).

Fedora's `ffmpeg-free` can omit `libx264`. In v3.9.1 the automatic, explicit
H.264, CPU and streaming paths can fall through to `libopenh264`, but only after
Turbo Recorder proves that encoder with a real one-frame test. Fedora's
`noopenh264` compatibility shim is deliberately rejected. With the Cisco
OpenH264 repository enabled, the normal install pulls the real implementation;
replace an existing stub with:

```bash
sudo dnf install ffmpeg-free
sudo dnf swap noopenh264 openh264
```

The second command requires the `fedora-cisco-openh264` repository to be
enabled. Alternatively, use another compatible `/usr/bin/ffmpeg` provider.

### BSD and other Unix

FreeBSD has a native package; every other Unix (OpenBSD, NetBSD, DragonFly,
illumos, macOS, or Linux) can use the portable tarball. Turbo Recorder is pure
Python plus a POSIX shell front-end, so one archive runs everywhere.

```sh
# FreeBSD — native package
pkg add ./turborec-3.9.1.pkg
pkg install python3 ffmpeg          # runtime prerequisites; screen via X11/XWayland

# Any Unix — portable tarball (installs to /usr/local by default)
tar xzf turborec-3.9.1.tar.gz && cd turborec-3.9.1
sudo ./install.sh                   # or: PREFIX="$HOME/.local" ./install.sh
```

On **OpenBSD** install the prerequisites with `pkg_add python3 ffmpeg`. Use the
equivalent Python 3, Tk and FFmpeg packages on NetBSD and DragonFly. The
tarball's `install.sh` prints any missing core prerequisite it detects.

Turbo Recorder identifies FreeBSD, OpenBSD, NetBSD and DragonFly separately.
BSD screen capture uses FFmpeg `x11grab` in an X11 session or through XWayland.
Microphones use an FFmpeg input that is genuinely compiled and backed by a real
character-device node: sndio is preferred on OpenBSD; OSS is preferred on
FreeBSD, NetBSD and DragonFly. PulseAudio is optional on BSD and is used only
when FFmpeg's Pulse input, a working `pactl` connection and real sources are all
available. A Pulse monitor source is required for BSD desktop/system audio.

Release archives have two different purposes: `turborec-3.9.1.tar.gz` is the
portable end-user installer above, while `turborec-3.9.1-source.tar.gz` is the
complete immutable tracked source tree, including tests, intended for ports and
distribution maintainers. Together with nine platform payloads and
`SHA256SUMS`, the release contains 11 assets in total.

### Linux — from source (works everywhere)

```bash
git clone https://github.com/cristiancmoises/turborec
cd turborec
python3 turborec.py gui        # or detect / record / devices / targets
```

Install Tk for the GUI: `sudo apt install python3-tk` (Debian/Ubuntu),
`sudo dnf install python3-tkinter` (Fedora), `sudo pacman -S tk` (Arch).

### GNU Guix

**Easiest — the package definition or the relocatable pack.** The repo ships a
`guix.scm`, and every release ships a relocatable pack tarball. Both give you a
working `turborec` CLI and Tk GUI with `ffmpeg`, `wf-recorder`, `pactl` and the
Python `tk` output wired into the environment:

```bash
# From the repo — build and/or install the package
guix build   -f guix.scm          # build it (prints the /gnu/store path)
guix package -f guix.scm          # install it into your profile
guix shell   -f guix.scm -- turborec detect   # run it ad-hoc

# Or the prebuilt relocatable pack from the Releases page (no Guix daemon needed
# to run it; unpacks the /gnu/store closure + a /bin/turborec launcher)
tar xf turborec-3.9.1-guix-x86_64.tar.gz -C /
/bin/turborec record -m video_both
```

The package build validates that Python can import `_tkinter`, and release CI
validates the packaged command paths. The GUI is intended to run on a graphical
Guix session; that headless build validation does not amount to a visual GUI or
physical capture-device test. Launch it normally:

```bash
turborec gui
# or, from the relocatable pack:
/bin/turborec gui
```

### macOS

Install [Python from python.org](https://www.python.org/downloads/) (it bundles
Tk) and [FFmpeg](https://ffmpeg.org/download.html), then run `python3 turborec.py gui`.
For system-audio capture, add a loopback device such as
[BlackHole](https://github.com/ExistentialAudio/BlackHole).

### Windows

Grab the single-file **`Turbo_Recorder-<version>-windows-x64.exe`** from the
[Releases](https://github.com/cristiancmoises/turborec/releases) page and run it.
It is **fully self-contained** — Python, Tk **and FFmpeg are bundled inside the
`.exe`** — so there is nothing else to install, no PATH to configure, and no
admin rights needed:

```powershell
Turbo_Recorder-3.9.1-windows-x64.exe gui        # or: detect / record / --help
```

Prefer a classic install with Start-Menu shortcuts and an uninstaller? Use
**`Turbo_Recorder-<version>-windows-x64-setup.exe`** — it is equally
self-contained: it bundles Python 3.12 (with Tk), FFmpeg and the app, installs
Python silently *only if* no Python 3.8+ with Tk is already present, and adds
"Turbo Recorder" under **Settings → Apps** for clean removal.

(The bundle carries its own FFmpeg; if you'd rather use a system FFmpeg, put it
on `PATH` and pass `--ffmpeg C:\path\to\ffmpeg.exe`.) The current release keeps
Unicode microphone/camera labels intact, records through stable DirectShow IDs, and
lists native monitors/windows even with negative multi-monitor coordinates.
Allow **Microphone** and **Camera** access for desktop apps under Windows
**Settings → Privacy & security**. For system-audio capture, enable a loopback
such as "Stereo Mix" / "Mixagem estéreo" or install
[VB-CABLE](https://vb-audio.com/Cable/).

Prefer running from source? Install [Python](https://www.python.org/downloads/)
(it bundles Tk) + [FFmpeg](https://ffmpeg.org/download.html) and run
`python turborec.py gui`.

---

## 2. 60-second quick start

```bash
turborec detect        # see what was auto-detected (OS, CPU, GPU, encoder, screen, devices)
turborec gui           # open the graphical app — pick options, press ● START, press ■ STOP
turborec record        # CLI: Best · Auto codec · 23 fps · 4K
```

Recordings go to `~/Videos` (video) or `~/Audio` (audio) with timestamped names
like `video_mic_2026-07-24_14-22-09.mkv`. Stop a CLI recording with **`q`** or
**Ctrl-C** — the file is finalized cleanly.

---

## 3. Core concepts

- **It auto-detects everything.** Run `turborec detect` to see your OS, display
  server, CPU vendor, GPU, the best usable codec/encoder candidates, your
  screen resolution, and your microphone + system-audio (loopback) sources.
- **Real-time, correct-speed capture.** Presets are tuned to keep up with a live
  source, and the output is forced to constant frame rate — so recordings always
  play back at the right speed and stay smooth, even at high resolution/fps.
- **Quality-first defaults.** Best quality, Auto codec, 23 fps and 4K output.
  Auto prefers usable hardware AV1 → HEVC → H.264, then safely falls back to
  software H.264. Audio is lossless FLAC and video carries BT.709 color metadata.
- **One engine, two front-ends:** the cross-platform `turborec` (CLI + GUI) and
  the lightweight Linux/X11 `turborecorder` bash script.

---

## 4. Using the GUI

Launch with `turborec gui` (or just `turborec` on a desktop), or pick **Turbo
Recorder** from your application menu.

```
┌──────────────────────────────────────────────────────────────┐
│ ● TURBO RECORDER          linux · x11 · nvidia HW · 3280x1200 │  ← live hardware status
├──────────────────────────────────────────────────────────────┤
│ CAPTURE                                                        │
│ [Screen+All][Screen+Mic][Screen+Sys][Screen]                  │  ← capture mode (segmented)
│ [Audio All][Mic][Sys]                                         │
│ Quality [best ▾]  Codec [auto ▾]  FPS [23 ▾]                  │
│ av1_nvenc · nvenc · hardware accelerated                      │  ← example chosen encoder
│ Source [ Full screen (3280x1200)        ▾] ⟳                  │  ← screen / monitor / window
│ Region [________]  blank = full screen                        │  ← optional exact override
│ Output resolution [4K (3840×2160) ▾]                           │
│ AUDIO                                                      ⟳   │
│ ● Microphone   [ Built-in / your mic           ▾]            │
│ ● System audio [ ...monitor                     ▾]            │
│ Audio codec    [ flac ▾]  lossless                            │
│ OUTPUT                                                        │
│ Folder [ /home/you/Videos              ] [ … ]               │
│ ↳ video_both_2026-06-13_14-22-09.mkv                         │  ← live filename preview
│ Encoder  [Auto][GPU][CPU]                                     │  ← CPU vs GPU
│ › command preview                                  copy       │  ← exact ffmpeg command
├──────────────────────────────────────────────────────────────┤
│ 00:00:00        ┌──────────────────┐                          │
│ idle            │   ●  START        │                          │
│ 0.0 MB          └──────────────────┘                          │
└──────────────────────────────────────────────────────────────┘
```

- **CAPTURE** — pick a mode (what to record), then Quality / Codec / FPS. The
  defaults are Best / Auto / 23; the cyan line shows the codec and encoder that
  passed the runtime probe.
- **Source** — full screen, a specific monitor, or a window (OBS-style). Press
  **⟳** to re-scan after opening/closing windows. **Region** is an advanced
  override (`WxH` or `WxH+X+Y`).
- **AUDIO** — your mic and system-audio source are pre-selected; the **⟳** button
  re-probes devices. Dots show whether a real device is selected.
- **OUTPUT** — choose the folder; the filename preview updates live.
- **Encoder** — `Auto` (default), `GPU` (request hardware) or `CPU` (force software).
- **command preview** — expand to see (and `copy`) the exact FFmpeg command.
- **Footer** — press **● START** to record. While recording you get a live
  **timer**, a pulsing **REC** indicator and the growing **file size**. Press
  **■ STOP** to finalize. Keyboard: **Space** or **Ctrl-R** start/stop, **Esc** stop.

---

## 5. Using the CLI

```text
turborec <subcommand> [options]

Subcommands:
  detect      probe the system and print capabilities   (--json for scripts)
  record      record screen and/or audio
  gui         launch the graphical interface
  devices     list microphones and system-audio sources (--json)
  encoders    list available video encoders per codec    (--json)
  targets     list capture targets: screen / monitors / windows (--json)
```

Most-used `record` options:

| Option | Meaning | Default |
|---|---|---|
| `-m, --mode` | what to capture (see [modes](#6-capture-modes)) | `auto` |
| `-q, --quality` | `best` · `high` · `balanced` · `compact` | `best` |
| `-c, --codec` | `auto` · `h264` · `hevc` · `av1` | `auto` |
| `-f, --fps` | frames per second | `23` |
| `-R, --resolution` | `native` · `720p` · `1080p` · `1440p` · `4k` | `4k` |
| `-o, --out` | output folder | `~/Videos` or `~/Audio` |
| `--backend` | `auto` · `gpu` · `cpu` (also `--gpu` / `--cpu`) | `auto` |
| `--monitor NAME` | capture a specific monitor | — |
| `--window TITLE` | capture a specific window | — |
| `--region WxH+X+Y` | capture an exact region | full screen |
| `--audio-codec` | `flac` · `aac` · `opus` | `flac` |
| `--audio-rate` | audio sample rate | `48000` |
| `--mic-device` / `--system-device` | pick devices by id/name | auto |
| `-t, --duration` | auto-stop (e.g. `90`, `5m`, `1m30s`, `2h`, `1h30`, `HH:MM:SS`) | — |
| `--countdown N` | wait N seconds before starting | `0` |
| `--open` | open the file when done | off |
| `--dry-run` | print the FFmpeg command and exit | off |

Global: `--ffmpeg PATH`, `--config FILE`, `--version`.

> **Tip:** add `--dry-run` to any `record` command to see the exact FFmpeg command
> without recording.

---

## 6. Capture modes

`-m/--mode` selects what to record:

| Mode | Captures |
|---|---|
| `auto` | best video mode supported by detected audio devices *(default)* |
| `video_both` | screen + microphone + system audio |
| `video_mic` | screen + microphone |
| `video_system` | screen + system audio |
| `video_only` | screen, no audio |
| `audio_both` | microphone + system audio (no video) |
| `audio_mic` | microphone only |
| `audio_system` | system audio only |

```bash
turborec record -m video_mic         # tutorial-style: screen + your voice
turborec record -m audio_both        # podcast-style: mic + desktop audio, lossless
```

---

## 7. Choosing what to capture

List everything that can be captured:

```bash
turborec targets
#   [screen]   Full screen  (3280x1200)   3280x1200+0+0
#   [monitor]  DP-4   (1920x1200)         1920x1200+0+0
#   [monitor]  HDMI-0 (1360x768)          1360x768+1920+0
#   [window]   My Browser (1280x800)      1280x800+200+100
```

Then:

```bash
turborec record --monitor HDMI-0                 # one monitor
turborec record --window "My Browser"            # one window (by title substring)
turborec record --region 1280x720+100+50         # an exact rectangle (WxH+X+Y)
```

In the **GUI**, use the **Source** dropdown (press **⟳** to refresh after opening
windows). Notes:

- On **X11**, window capture grabs that window's *screen region* (like OBS
  "Display Capture" cropped to the window) — if another window overlaps it, the
  overlap is captured too.
- On **Linux Wayland** (sway/Hyprland/river), capture uses `wf-recorder` automatically.
  Pick an output with `--monitor <name>` (or the Source dropdown); a region with
  `--region`; a sway window with `--window`. NVENC isn't available through
  `wf-recorder`, so encoding is software `libx264`/`libx265` (real-time at 1080p).
  `video_both` records perfectly A/V-synced via a temporary PipeWire combined
  source. (Install `wf-recorder` if it's missing.)
- On the **BSDs**, use an X11 session or XWayland. X11 retains the `x11grab`
  screen, monitor, visible-window and region targets. XWayland can capture the
  screen/region it exposes, subject to compositor policy; native Linux
  `wf-recorder` integration is not claimed for BSD Wayland sessions.

---

## 8. Choosing how to encode

### CPU vs GPU

```bash
turborec record --gpu      # request hardware (NVENC / Quick Sync / VAAPI / AMF / VideoToolbox)
turborec record --cpu      # force software (including verified OpenH264 fallback)
turborec record            # auto: hardware if available, else software
```

GPU encoding is much lighter on the CPU and is the default when available. CPU
encoding is the universal fallback and is fine for smaller regions / lower fps.

### Quality presets

`-q best|high|balanced|compact` (highest → smallest). All presets are tuned to
record in **real time**; `best` favors quality, `compact` favors file size.

### Codec

`-c auto|h264|hevc|av1`. **auto** is the default and selects the first usable
hardware encoder in quality/efficiency order: **AV1 → HEVC → H.264**. If none is
usable, it falls back to software H.264 so recording still works. Explicit
**h264** is the most compatible; **hevc** (H.265) and **av1** can produce smaller
files at comparable visual quality when your hardware, FFmpeg and player support
them. See what your machine exposes:

```bash
turborec encoders          # shows the best h264/hevc/av1 encoder for your machine
```

### Output resolution (record in 4K)

`-R native|720p|1080p|1440p|4k` (GUI: the **Output** dropdown). `4k` is the
default and produces an exact 3840×2160 frame. Turbo Recorder scales with
high-quality **lanczos** while preserving aspect ratio and padding as needed.
Choose `native` to preserve the captured dimensions and reduce processing load:

```bash
turborec record                          # Best · Auto codec · 23 fps · 4K
turborec record -R native                # preserve the source dimensions
turborec record -R 1080p                 # normalize to 1920×1080
```

> **Why upscale to 4K for YouTube?** YouTube picks the quality tier — and,
> crucially, the **bitrate budget** — from the *uploaded* resolution. A native
> 1920×1200 screen capture can land at a low tier (720p/1080p) with heavy
> compression, while the same content uploaded as 4K gets the high-bitrate 4K
> pipeline and looks dramatically better at every playback quality.

---

## 9. Audio

- **Lossless by default:** `--audio-codec flac`. Use `aac` (320k) or `opus` (256k)
  for smaller files.
- Mic + system audio are **mixed cleanly** with a high-quality **soxr** resampler.
- **Sound only on one side? `--audio-channels`.** Some inputs (a mono mic wired to
  one channel of a stereo interface — e.g. a Focusrite input 2) put audio on just
  one channel, so recordings play only left or right. Fix it:
  - `--audio-channels right` (or `left`) — clone that channel to **both** sides at
    full level.
  - `--audio-channels mono` — average both channels onto both sides (clip-safe).
  - `--audio-channels stereo` — leave the source untouched (default).

  In the GUI, use the **Channels** dropdown next to the audio codec.
- Pick specific devices:

```bash
turborec devices                                  # list mics + system-audio sources
turborec record -m audio_mic --mic-device "USB Microphone"
turborec record -m video_system --system-device "...monitor"
turborec record -m video_mic --audio-channels right   # fix right-only audio
```

> **Recording desktop/system audio** needs a loopback/monitor source: PulseAudio/
> PipeWire `*.monitor` on Linux, BlackHole/Loopback on macOS, "Stereo Mix" on
> Windows, or a working PulseAudio monitor on BSD. Native sndio/OSS device nodes
> provide microphone/input capture on BSD, not desktop loopback. `turborec
> devices` shows only what is actually available.

### Noise suppression (NoiseTorch-style, built in)

Reduce microphone background noise (fans, hiss, room tone) with one switch — no
NoiseTorch app, model file, or virtual device needed. It's applied to the
**microphone only**, never to your clean system audio, and works in recordings
and streams:

```bash
turborec record -m video_mic --denoise light     # gentle
turborec record -m video_mic --denoise medium    # recommended
turborec record -m video_mic --denoise strong    # aggressive (very noisy rooms)
```

In the GUI use the **Denoise** dropdown next to the audio codec. Under the hood
it uses FFmpeg's adaptive `afftdn` denoiser plus a high-pass filter.

### Webcam overlay (picture-in-picture)

Overlay your camera on the recording or stream, OBS-style:

```bash
turborec cameras                                             # list webcams
turborec record -m video_both --camera /dev/video0 \
    --camera-size medium --camera-position bottom-right
```

- `--camera` — `/dev/videoN` on Linux, or on BSD only when FFmpeg exposes V4L2
  and the path resolves to a real device; an AVFoundation index on macOS; or a
  DirectShow name on Windows. In the GUI: the **Webcam** dropdown.
- `--camera-size` — `small` / `medium` / `large`, an explicit `WxH`, or `N%` of
  the output width.
- `--camera-position` — `top-left`, `top-right`, `bottom-left`, `bottom-right`,
  or `center`.

It works on every backend and combines with streaming (`--stream KEY --camera …`)
so you can go live with your camera and clean audio in one command.

---

## 10. Live streaming to YouTube

Turbo Recorder can **go live** the same way OBS does — with your YouTube
**stream key** — no extra software.

**Get your key:** in **YouTube Studio → Create → Go live → Stream**, copy the
**Stream key** (looks like `xxxx-xxxx-xxxx-xxxx-xxxx`).

**GUI:** paste it into the **Stream key** field (it shows as dots) and press
**Start**. The status turns to **● LIVE**; press **Stop** to end.

**CLI:**

```bash
# Go live with screen + mic + system audio
turborec record -m video_both --stream YOUR_YT_STREAM_KEY

# Video + mic only
turborec record -m video_mic --stream YOUR_YT_STREAM_KEY

# A different service / custom ingest (Twitch, Restream, your own RTMP server)
turborec record --stream KEY --stream-url rtmp://live.twitch.tv/app
```

Press **`q`** or **Ctrl-C** to stop streaming.

**What it does for you.** Streaming has different requirements than recording to
a file, so Turbo Recorder switches the pipeline automatically:

- **H.264** video at **constant bitrate** (YouTube's recommended rate for your
  frame size — e.g. ~4.5–9 Mbps at 1080p), regardless of the `-c` codec you'd use
  for a file.
- **AAC** audio, 48 kHz stereo, with mic + system mixed just like a recording.
- A **2-second keyframe interval** (GOP = 2×fps) and **FLV over RTMPS**, which is
  what YouTube expects.
- Video-only modes still get a **silent audio track** so YouTube always sees audio.
- On **Linux Wayland**, `wf-recorder` encodes into a pipe that ffmpeg pushes, so live
  streaming works on wlroots compositors too.

Choose a resolution with `-R` (e.g. `-R 1080p`) exactly as for recording; the
bitrate follows the frame size.

> 🔒 **Your stream key is a credential.** Turbo Recorder redacts it (`••••`) from
> every printed command, the `--dry-run` output, the GUI preview, and the
> end-of-stream status line. As with any ffmpeg RTMP push, the key is present in
> the process's command line, so on a **shared multi-user machine** other local
> users could read it from the process list while you're live — Turbo Recorder
> prints a one-line note when you go live to remind you. On a personal machine
> this isn't a concern. Only pass `--stream-url` values you trust (it's
> restricted to `rtmp://` / `rtmps://`).

---

## 11. Timed recording, countdown and auto-open

```bash
turborec record -t 30                 # stop after 30 seconds
turborec record -t 5m                 # 5 minutes  (also 1m30s, 2h, 1h30, 00:05:00)
turborec record --countdown 3         # 3-2-1 before it starts
turborec record -t 1m --open          # record 1 min, then open the file
```

---

## 12. Saving your defaults

Put a JSON file at `~/.config/turborec/config.json` (or point `--config` / the
`$TURBOREC_CONFIG` env var at one). Any CLI flag overrides the file.

```json
{
  "quality": "high",
  "fps": 30,
  "codec": "hevc",
  "audio_codec": "opus",
  "backend": "gpu",
  "out": "/home/you/Recordings"
}
```

```bash
turborec record                                   # uses the config defaults
turborec record -q best                           # config + this override
turborec --config ./project.json record           # a project-specific config
```

---

## 13. The Linux bash recorder

`turborecorder` is a fast, dependency-light path for X11 (FFmpeg + `xrandr`/
`xdpyinfo` + PulseAudio/PipeWire). It auto-detects CPU/GPU, the best encoder, your
screen size, and your default mic + system-audio sources.

```bash
turborecorder                          # interactive menu
turborecorder -m video_both -Q best    # screen + mic + system audio, best quality
turborecorder -m video_mic -C hevc -f 30
turborecorder -S                       # force software (CPU) encoding
turborecorder -h                       # all options
```

Override audio sources with `MONITOR_SOURCE=` / `MIC_SOURCE=` env vars if needed.

---

## 14. Recipes and cookbook

```bash
# Tutorial / screencast with your voice (GPU), 30 fps, stop after 10 min
turborec record -m video_mic --gpu -f 30 -t 10m

# Gameplay at max quality, H.265 to save space
turborec record -m video_both -c hevc -q best

# Just one monitor, system audio only (no mic)
turborec record -m video_system --monitor DP-4

# A single window, no audio, then open it
turborec record -m video_only --window "Slides" --open

# Lossless podcast: mic + desktop audio mixed, FLAC
turborec record -m audio_both --audio-codec flac

# Lightweight CPU capture of a small region
turborec record --cpu --region 1280x720+0+0 -q balanced

# See the exact ffmpeg command first
turborec record -m video_both --dry-run
```

---

## 15. Tips for the best possible quality

- **Leave codec and backend on Auto** for the quality-first hardware path. Use
  `--gpu` to request hardware explicitly; Turbo Recorder still warns and takes
  the safe software fallback if no hardware candidate passes its probe.
- **Match FPS to your content.** The 23 fps default prioritizes detail per frame
  and keeps load down; use 30 fps for talks/slides or 60 fps for fast motion and
  gameplay.
- **`-q best`** plus **FLAC** audio for archival masters; transcode later if needed.
- **HEVC/AV1** (`-c hevc` / `-c av1`) for much smaller files at the same quality,
  if your players support them.
- **4K output is the default** for a quality-first master and YouTube upload.
  Use **`-R native`** to preserve source pixels or reduce encoding load. YouTube
  assigns its quality tier and bitrate budget from the uploaded resolution, so
  a 4K upload keeps your video sharp (see
  [§8 Output resolution](#output-resolution-record-in-4k)).
- If a recording is ever choppy, drop to `-q high`/`-f 30` or a smaller `--region`
  to give the encoder more headroom (see Troubleshooting).

---

## 16. Troubleshooting

**The video plays in slow motion / looks laggy.**
Fixed in 2.2.0 (real-time presets + forced constant frame rate). Make sure you're
on the latest version (`turborec --version`). If it's still choppy on very heavy
content, give the encoder headroom: `--gpu`, lower `-f` (e.g. 30), `-q high`, or a
smaller `--region`.

**`Tkinter is not available` when opening the GUI.**
Install Tk: `sudo apt install python3-tk` (Debian/Ubuntu),
`sudo dnf install python3-tkinter` (Fedora), `sudo pacman -S tk` (Arch). On Guix,
see [Install → GNU Guix](#1-install). The CLI works without Tk.

**`FFmpeg not found`.** Install FFmpeg and ensure it's on your `PATH`
(`ffmpeg -version`). Point at a specific binary with `--ffmpeg /path/to/ffmpeg`.

**No system audio is recorded.** You need a loopback/monitor source — see
[Audio](#9-audio). Run `turborec devices` to confirm one exists.

**Microphone requested but none found.** Select one explicitly:
`turborec record --mic-device "<name from turborec devices>"`.

**BSD microphone is not listed.** First inspect the FFmpeg build with
`ffmpeg -hide_banner -devices` and the nodes with `ls -l /dev/audio* /dev/dsp*`.
OpenBSD normally uses the `sndio` input; FreeBSD, NetBSD and DragonFly normally
use `oss`. Turbo Recorder lists a native source only when both the FFmpeg input
and a real character-device node exist. Do not use `--system-device` with a
native sndio/OSS microphone node: desktop audio needs an actual Pulse monitor
shown by `turborec devices`.

**Linux Wayland: "wf-recorder is not installed".** Install it
(`sudo apt install wf-recorder` / `sudo dnf install wf-recorder` /
`guix install wf-recorder`). turborec uses it to capture wlroots compositors
(sway/Hyprland/river); a black/empty recording usually means an old version
falling back to `x11grab` — upgrade to 3.0.0+.

**Window capture also shows overlapping windows.** Expected on X11 — it captures
the window's screen region. Keep the target window unobstructed, or capture a
monitor/region instead.

**It crashed / behaved unexpectedly.** Re-run with `--dry-run` to inspect the exact
FFmpeg command, and `turborec detect` to confirm what was detected.

---

## 17. FAQ

**Where are my recordings?** `~/Videos` for video, `~/Audio` for audio, with
timestamped names. Change with `-o /path` or the GUI Output folder.

**Does it work on multiple monitors?** Yes — `turborec targets` lists each
monitor; capture one with `--monitor NAME` or pick it in the GUI **Source** menu.

**How do I record a specific window like OBS?** `--window "Title"` (CLI) or the
**Source** dropdown (GUI). See [§7](#7-choosing-what-to-capture).

**Can I record just audio?** Yes — `-m audio_mic`, `-m audio_system`, or
`-m audio_both`.

**How do I stop a CLI recording?** Press **`q`** or **Ctrl-C**, or use `-t` for a
fixed length. The file is always finalized cleanly.

**Is it really lossless?** Audio is lossless with FLAC (default). Video uses
visually-lossless constant-quality encoding at `-q best`; for true lossless video,
use `--cpu -c h264` and a low CRF via a custom FFmpeg command (see `--dry-run`).

---

Made for fast, high-quality recording on every OS. Happy recording! 🎬
