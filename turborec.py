#!/usr/bin/env python3
# =============================================================================
#  TURBO RECORDER — cross-platform, hardware-accelerated screen & audio recorder
#
#  One file. No third-party Python dependencies (stdlib only). Needs FFmpeg.
#
#  It automatically detects, on Linux / macOS / Windows:
#    * the operating system and display server (X11 / Wayland / Quartz / GDI)
#    * the CPU vendor (Intel / AMD / Apple Silicon)
#    * the GPU and the best available hardware video encoder
#        NVIDIA NVENC · Intel QSV · VAAPI · AMD AMF · Apple VideoToolbox · x264
#    * the primary screen resolution
#    * the default microphone and the system-audio (monitor/loopback) source
#
#  Then it builds a state-of-the-art FFmpeg pipeline for the best quality your
#  hardware can deliver and runs it.  Use the CLI (`turborec.py ...`) or the
#  graphical interface (`turborec.py gui`).
#
#  License: GPL-3.0 (same as the project).
# =============================================================================
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

APP_NAME = "Turbo Recorder"
VERSION = "3.4.0"

# ---------------------------------------------------------------------------
# Small terminal helpers
# ---------------------------------------------------------------------------
_USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t: str) -> str:
    return _c("1", t)


def dim(t: str) -> str:
    return _c("2", t)


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def red(t: str) -> str:
    return _c("31", t)


def cyan(t: str) -> str:
    return _c("36", t)


def info(msg: str) -> None:
    print(f"{cyan('::')} {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"{yellow('!!')} {msg}", file=sys.stderr)


def err(msg: str) -> None:
    print(f"{red('xx')} {msg}", file=sys.stderr)


def die(msg: str, code: int = 1) -> "None":
    err(msg)
    sys.exit(code)


def run_cmd(cmd: list[str], timeout: float = 8.0) -> str:
    """Run a command and return stdout+stderr text, '' on any failure."""
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
            errors="replace",
        )
        return p.stdout or ""
    except (subprocess.SubprocessError, OSError):
        return ""


def _san(s: str) -> str:
    """Strip control / escape characters from externally-sourced text (window
    titles, device labels) so they can't inject terminal escape sequences."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "", s or "")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class AudioDevice:
    id: str          # backend identifier passed to ffmpeg
    label: str       # human readable
    is_monitor: bool = False  # True for system-audio / loopback / monitor


@dataclass
class CaptureTarget:
    kind: str                  # screen | monitor | window | region
    label: str                 # human readable
    geometry: Optional[str] = None   # "WxH+X+Y" region of the desktop
    win_title: Optional[str] = None  # native window title (Windows gdigrab)
    output: Optional[str] = None     # Wayland output name (wf-recorder -o)
    wl_geometry: Optional[str] = None  # wf-recorder region "X,Y WxH" within output


@dataclass
class SystemInfo:
    os: str = ""                 # linux | macos | windows
    display_server: str = ""     # x11 | wayland | quartz | gdi
    cpu_vendor: str = ""         # intel | amd | apple | unknown
    cpu_model: str = ""
    gpu_vendor: str = ""         # nvidia | intel | amd | apple | unknown
    gpu_model: str = ""
    has_gpu: bool = False
    vaapi_device: str = ""       # /dev/dri/renderD128 on Linux
    screen: str = ""             # WxH
    ffmpeg: str = "ffmpeg"
    encoders: set[str] = field(default_factory=set)
    mics: list[AudioDevice] = field(default_factory=list)
    monitors: list[AudioDevice] = field(default_factory=list)
    default_mic: Optional[AudioDevice] = None
    default_monitor: Optional[AudioDevice] = None
    # Wayland / wlroots capture (sway, Hyprland, river, …)
    wayland_recorder: str = ""   # path to wf-recorder, or "" if unavailable
    wl_outputs: list = field(default_factory=list)  # CaptureTarget per output
    wl_default_output: str = ""  # focused/primary output name


# ---------------------------------------------------------------------------
# FFmpeg discovery
# ---------------------------------------------------------------------------
def _use_bundled_binaries() -> None:
    """When running as a frozen (PyInstaller) build, expose the binaries shipped
    inside the bundle — e.g. ffmpeg.exe on Windows — so the app is fully
    self-contained and needs no separately-installed ffmpeg.

    Security: for a --onefile build the bundled binaries are extracted into the
    private, per-process ``sys._MEIPASS`` dir; that is the ONLY directory added.
    We deliberately do NOT add ``dirname(sys.executable)`` for onefile builds —
    that is wherever the portable .exe was dropped (often the Downloads folder),
    and putting it on PATH would let an unrelated planted binary (e.g. a rogue
    ``nvidia-smi.exe``) be resolved from an untrusted location. For a onedir
    build there is no _MEIPASS and the binaries genuinely sit next to the .exe.
    In both cases the directory is added only if it actually contains our bundled
    ffmpeg, so no unrelated directory is ever placed on PATH.
    """
    if not getattr(sys, "frozen", False):
        return
    bundle_dir = getattr(sys, "_MEIPASS", None) \
        or os.path.dirname(os.path.abspath(sys.executable))
    ffname = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if os.path.isdir(bundle_dir) and os.path.isfile(os.path.join(bundle_dir, ffname)):
        os.environ["PATH"] = bundle_dir + os.pathsep + os.environ.get("PATH", "")


def find_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def list_encoders(ffmpeg: str) -> set[str]:
    out = run_cmd([ffmpeg, "-hide_banner", "-encoders"])
    found: set[str] = set()
    for line in out.splitlines():
        m = re.match(r"\s*[A-Z.]{6}\s+(\S+)", line)
        if m:
            found.add(m.group(1))
    return found


# ---------------------------------------------------------------------------
# OS / display server
# ---------------------------------------------------------------------------
def detect_os() -> str:
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s.startswith("win"):
        return "windows"
    return "linux"


def detect_display_server(os_name: str) -> str:
    if os_name == "macos":
        return "quartz"
    if os_name == "windows":
        return "gdi"
    # linux
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    return "x11"


# ---------------------------------------------------------------------------
# CPU vendor
# ---------------------------------------------------------------------------
def detect_cpu(os_name: str) -> tuple[str, str]:
    vendor, model = "unknown", platform.processor() or platform.machine()
    if os_name == "linux":
        try:
            with open("/proc/cpuinfo", "r", errors="replace") as fh:
                txt = fh.read()
            mv = re.search(r"vendor_id\s*:\s*(\S+)", txt)
            mm = re.search(r"model name\s*:\s*(.+)", txt)
            if mm:
                model = mm.group(1).strip()
            if mv:
                vid = mv.group(1)
                if "Intel" in vid:
                    vendor = "intel"
                elif "AMD" in vid:
                    vendor = "amd"
        except OSError:
            pass
    elif os_name == "macos":
        if platform.machine() == "arm64":
            vendor = "apple"
            model = run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or "Apple Silicon"
        else:
            vendor = "intel"
            model = run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or model
    elif os_name == "windows":
        ident = (os.environ.get("PROCESSOR_IDENTIFIER", "") + " " + model)
        if "Intel" in ident or "GenuineIntel" in ident:
            vendor = "intel"
        elif "AMD" in ident or "AuthenticAMD" in ident:
            vendor = "amd"
    return vendor, model


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------
def _linux_first_dri_render() -> str:
    dri = "/dev/dri"
    try:
        nodes = sorted(n for n in os.listdir(dri) if n.startswith("renderD"))
        if nodes:
            return os.path.join(dri, nodes[0])
    except OSError:
        pass
    return ""


def detect_gpu(os_name: str) -> tuple[str, str, bool, str]:
    """Return (vendor, model, has_gpu, vaapi_device)."""
    vendor, model, vaapi = "unknown", "", ""
    has = False

    # NVIDIA is detectable everywhere via nvidia-smi
    if shutil.which("nvidia-smi"):
        name = run_cmd(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]).strip()
        if name:
            return "nvidia", name.splitlines()[0].strip(), True, ""

    if os_name == "linux":
        vaapi = _linux_first_dri_render()
        out = run_cmd(["sh", "-c", "lspci -nn 2>/dev/null | grep -iE 'vga|3d|display'"])
        low = out.lower()
        if "nvidia" in low:
            vendor = "nvidia"
        elif "advanced micro devices" in low or "amd/ati" in low or " amd " in low or "radeon" in low:
            vendor = "amd"
        elif "intel" in low:
            vendor = "intel"
        if out.strip():
            model = out.strip().splitlines()[0]
            model = re.sub(r"^\S+\s+", "", model)
        has = bool(vaapi) or vendor != "unknown"
    elif os_name == "macos":
        out = run_cmd(["system_profiler", "SPDisplaysDataType"])
        m = re.search(r"Chipset Model:\s*(.+)", out)
        model = m.group(1).strip() if m else "Apple GPU"
        vendor = "apple"
        has = True
    elif os_name == "windows":
        out = run_cmd([
            "powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_VideoController).Name",
        ])
        if not out.strip():
            out = run_cmd(["wmic", "path", "win32_VideoController", "get", "name"])
        low = out.lower()
        if "nvidia" in low:
            vendor = "nvidia"
        elif "amd" in low or "radeon" in low:
            vendor = "amd"
        elif "intel" in low:
            vendor = "intel"
        lines = [l.strip() for l in out.splitlines() if l.strip() and l.strip().lower() != "name"]
        model = lines[0] if lines else ""
        has = vendor != "unknown" or bool(model)
    return vendor, model, has, vaapi


# ---------------------------------------------------------------------------
# Screen size
# ---------------------------------------------------------------------------
def detect_screen(os_name: str, display_server: str) -> str:
    if os_name == "linux":
        if shutil.which("xdpyinfo"):
            out = run_cmd(["xdpyinfo"])
            m = re.search(r"dimensions:\s*(\d+x\d+)", out)
            if m:
                return m.group(1)
        if shutil.which("xrandr"):
            out = run_cmd(["xrandr", "--query"])
            m = re.search(r"\bconnected\b.*?(\d+)x(\d+)\+", out)
            if m:
                return f"{m.group(1)}x{m.group(2)}"
        if shutil.which("wlr-randr"):
            out = run_cmd(["wlr-randr"])
            m = re.search(r"(\d+)x(\d+)\s+px", out)
            if m:
                return f"{m.group(1)}x{m.group(2)}"
    elif os_name == "macos":
        out = run_cmd(["system_profiler", "SPDisplaysDataType"])
        m = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", out)
        if m:
            return f"{m.group(1)}x{m.group(2)}"
    elif os_name == "windows":
        try:
            import ctypes  # noqa: PLC0415

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            user32.SetProcessDPIAware()
            return f"{user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}"
        except Exception:  # noqa: BLE001
            pass
    return ""


# ---------------------------------------------------------------------------
# Audio devices
# ---------------------------------------------------------------------------
def _detect_audio_linux() -> tuple[list[AudioDevice], list[AudioDevice], Optional[AudioDevice], Optional[AudioDevice]]:
    mics: list[AudioDevice] = []
    monitors: list[AudioDevice] = []
    if not shutil.which("pactl"):
        return mics, monitors, None, None
    default_sink = run_cmd(["pactl", "get-default-sink"]).strip()
    default_src = run_cmd(["pactl", "get-default-source"]).strip()
    out = run_cmd(["pactl", "list", "short", "sources"])
    for line in out.splitlines():
        cols = line.split("\t")
        if len(cols) < 2:
            continue
        name = cols[1]
        dev = AudioDevice(id=name, label=name, is_monitor=name.endswith(".monitor"))
        if dev.is_monitor:
            monitors.append(dev)
        else:
            mics.append(dev)
    def_mic = next((m for m in mics if m.id == default_src), mics[0] if mics else None)
    want_mon = (default_sink + ".monitor") if default_sink else ""
    def_mon = next((m for m in monitors if m.id == want_mon), monitors[0] if monitors else None)
    return mics, monitors, def_mic, def_mon


def _parse_avfoundation_devices(text: str) -> tuple[list[str], list[str]]:
    """Return (video_devices, audio_devices) as 'index: name' strings."""
    video, audio, section = [], [], None
    for line in text.splitlines():
        if "AVFoundation video devices" in line:
            section = "v"
            continue
        if "AVFoundation audio devices" in line:
            section = "a"
            continue
        m = re.search(r"\[(\d+)\]\s+(.+)$", line)
        if m and section:
            entry = f"{m.group(1)}: {m.group(2).strip()}"
            (video if section == "v" else audio).append(entry)
    return video, audio


def _detect_audio_macos(ffmpeg: str) -> tuple[list[AudioDevice], list[AudioDevice], Optional[AudioDevice], Optional[AudioDevice]]:
    out = run_cmd([ffmpeg, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""])
    _, audio = _parse_avfoundation_devices(out)
    mics: list[AudioDevice] = []
    monitors: list[AudioDevice] = []
    for entry in audio:
        idx, _, name = entry.partition(": ")
        is_mon = any(k in name.lower() for k in ("blackhole", "soundflower", "loopback", "aggregate"))
        dev = AudioDevice(id=idx, label=name, is_monitor=is_mon)
        (monitors if is_mon else mics).append(dev)
    return mics, monitors, (mics[0] if mics else None), (monitors[0] if monitors else None)


def _detect_audio_windows(ffmpeg: str) -> tuple[list[AudioDevice], list[AudioDevice], Optional[AudioDevice], Optional[AudioDevice]]:
    out = run_cmd([ffmpeg, "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"])
    mics: list[AudioDevice] = []
    monitors: list[AudioDevice] = []
    audio_section = False
    for line in out.splitlines():
        if "DirectShow audio devices" in line:
            audio_section = True
            continue
        if "DirectShow video devices" in line:
            audio_section = False
            continue
        m = re.search(r'"([^"]+)"', line)
        if m and audio_section:
            name = m.group(1)
            is_mon = any(k in name.lower() for k in ("stereo mix", "what u hear", "loopback", "virtual"))
            dev = AudioDevice(id=name, label=name, is_monitor=is_mon)
            (monitors if is_mon else mics).append(dev)
    return mics, monitors, (mics[0] if mics else None), (monitors[0] if monitors else None)


def detect_audio(os_name: str, ffmpeg: str):
    if os_name == "linux":
        return _detect_audio_linux()
    if os_name == "macos":
        return _detect_audio_macos(ffmpeg)
    if os_name == "windows":
        return _detect_audio_windows(ffmpeg)
    return [], [], None, None


# ---------------------------------------------------------------------------
# Capture targets — full screen, each monitor, and (OBS-style) windows
# ---------------------------------------------------------------------------
def _detect_monitors_x11() -> list[CaptureTarget]:
    out = run_cmd(["xrandr", "--listmonitors"])
    targets: list[CaptureTarget] = []
    # e.g. " 0: +*eDP-1 2560/697x1440/392+0+0  eDP-1"
    for line in out.splitlines():
        m = re.search(r"\b(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)\s+(\S+)\s*$", line)
        if m:
            w, h, x, y, name = m.groups()
            targets.append(CaptureTarget(
                kind="monitor", label=f"{name}  ({w}x{h})",
                geometry=f"{w}x{h}+{x}+{y}"))
    return targets


def _detect_windows_x11() -> list[CaptureTarget]:
    if not shutil.which("wmctrl"):
        return []
    out = run_cmd(["wmctrl", "-lG"])
    targets: list[CaptureTarget] = []
    for line in out.splitlines():
        # id desktop x y w h host title...
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        _id, desk, x, y, w, h, _host, title = parts
        if desk == "-1":      # sticky/utility windows (panels, docks)
            continue
        try:
            iw, ih = int(w), int(h)
        except ValueError:
            continue
        if iw < 64 or ih < 64:
            continue
        title = _san(title)
        short = (title[:48] + "…") if len(title) > 49 else title
        targets.append(CaptureTarget(
            kind="window", label=f"{short}  ({w}x{h})",
            geometry=f"{w}x{h}+{x}+{y}", win_title=title))
    return targets


def _detect_outputs_wayland() -> tuple[list[CaptureTarget], str]:
    """Wayland (wlroots) outputs via swaymsg, falling back to wlr-randr.

    Returns (monitor targets, focused output name). Geometry is global layout
    coords 'WxH+X+Y'; wf-recorder selects an output with -o.
    """
    targets: list[CaptureTarget] = []
    focused = ""
    if shutil.which("swaymsg"):
        out = run_cmd(["swaymsg", "-t", "get_outputs"])
        try:
            for o in json.loads(out):
                if not o.get("active"):
                    continue
                r = o.get("rect", {})
                name = o.get("name", "")
                w, h, x, y = r.get("width"), r.get("height"), r.get("x", 0), r.get("y", 0)
                if not (name and w and h):
                    continue
                targets.append(CaptureTarget(
                    kind="monitor", label=f"{name}  ({w}x{h})",
                    geometry=f"{w}x{h}+{x}+{y}", output=name))
                if o.get("focused"):
                    focused = name
        except (ValueError, TypeError):
            pass
    if not targets and shutil.which("wlr-randr"):
        out = run_cmd(["wlr-randr"])
        name = None
        size = None
        pos = "0,0"
        for line in out.splitlines():
            m = re.match(r"^(\S+)\s+\"", line)
            if m:
                # flush the previous output before starting a new one
                if name and size:
                    px, py = pos.split(",")
                    targets.append(CaptureTarget(
                        kind="monitor", label=f"{_san(name)}  ({size})",
                        geometry=f"{size}+{px}+{py}", output=name))
                name, size, pos = m.group(1), None, "0,0"
            mm = re.search(r"(\d+)x(\d+)\s+px.*current", line)
            if mm:
                size = f"{mm.group(1)}x{mm.group(2)}"
            mp = re.search(r"Position:\s*(\d+),(\d+)", line)
            if mp:
                pos = f"{mp.group(1)},{mp.group(2)}"
        if name and size:        # flush the last output
            px, py = pos.split(",")
            targets.append(CaptureTarget(
                kind="monitor", label=f"{_san(name)}  ({size})",
                geometry=f"{size}+{px}+{py}", output=name))
    if not focused and targets:
        focused = targets[0].output or ""
    return targets, focused


def _detect_windows_wayland() -> list[CaptureTarget]:
    """Capturable windows on sway via the i3/sway tree (best-effort)."""
    if not shutil.which("swaymsg"):
        return []
    out = run_cmd(["swaymsg", "-t", "get_tree"])
    targets: list[CaptureTarget] = []
    try:
        tree = json.loads(out)
    except ValueError:
        return targets

    def walk(node, output_name):
        on = node.get("name") if node.get("type") == "output" else output_name
        is_win = node.get("pid") and node.get("type") in ("con", "floating_con")
        if is_win:
            r = node.get("rect", {})
            w, h, x, y = r.get("width", 0), r.get("height", 0), r.get("x", 0), r.get("y", 0)
            title = _san(node.get("name") or node.get("app_id") or "window")
            if w >= 64 and h >= 64 and node.get("visible", True):
                short = (title[:46] + "…") if len(title) > 47 else title
                targets.append(CaptureTarget(
                    kind="window", label=f"{short}  ({w}x{h})",
                    geometry=f"{w}x{h}+{x}+{y}", output=on))
        for key in ("nodes", "floating_nodes"):
            for child in node.get(key, []):
                walk(child, on)

    walk(tree, "")
    return targets


def detect_capture_targets(si: SystemInfo) -> list[CaptureTarget]:
    """Full screen first, then each monitor, then capturable windows."""
    if si.os == "linux" and si.display_server == "wayland":
        outs, focused = _detect_outputs_wayland()
        foc = next((o for o in outs if o.output == focused), (outs[0] if outs else None))
        screen = CaptureTarget(
            kind="screen", label=f"Full screen  ({foc.output})" if foc else "Full screen",
            geometry=foc.geometry if foc else (f"{si.screen}+0+0" if si.screen else None),
            output=foc.output if foc else None)
        targets = [screen]
        if len(outs) > 1:        # multiple monitors: list each; one == full screen
            targets += outs
        targets += _detect_windows_wayland()
        return targets

    targets: list[CaptureTarget] = [
        CaptureTarget(kind="screen",
                      label=f"Full screen  ({si.screen})" if si.screen else "Full screen",
                      geometry=(f"{si.screen}+0+0" if si.screen else None))
    ]
    if si.os == "linux" and si.display_server == "x11":
        mons = _detect_monitors_x11()
        if len(mons) > 1:        # a single monitor == full screen; don't duplicate
            targets += mons
        targets += _detect_windows_x11()
    return targets


# ---------------------------------------------------------------------------
# Full system probe
# ---------------------------------------------------------------------------
def probe_system(ffmpeg: Optional[str] = None) -> SystemInfo:
    ff = ffmpeg or find_ffmpeg()
    if not ff:
        die("FFmpeg not found on PATH. Install it from https://ffmpeg.org/download.html")
    si = SystemInfo(ffmpeg=ff)
    si.os = detect_os()
    si.display_server = detect_display_server(si.os)
    si.cpu_vendor, si.cpu_model = detect_cpu(si.os)
    si.gpu_vendor, si.gpu_model, si.has_gpu, si.vaapi_device = detect_gpu(si.os)
    si.screen = detect_screen(si.os, si.display_server)
    si.encoders = list_encoders(ff)
    si.mics, si.monitors, si.default_mic, si.default_monitor = detect_audio(si.os, ff)
    # Wayland (wlroots) capture backend
    if si.os == "linux" and si.display_server == "wayland":
        si.wayland_recorder = shutil.which("wf-recorder") or ""
        si.wl_outputs, si.wl_default_output = _detect_outputs_wayland()
        if not si.screen and si.wl_outputs:
            # global desktop bounding box from output rects
            mx = my = 0
            for t in si.wl_outputs:
                m = re.match(r"(\d+)x(\d+)\+(\d+)\+(\d+)", t.geometry or "")
                if m:
                    mx = max(mx, int(m.group(3)) + int(m.group(1)))
                    my = max(my, int(m.group(4)) + int(m.group(2)))
            if mx and my:
                si.screen = f"{mx}x{my}"
    return si


# ---------------------------------------------------------------------------
# Encoder selection — pick the best available hardware path
# ---------------------------------------------------------------------------
@dataclass
class EncoderChoice:
    name: str            # ffmpeg encoder, e.g. h264_nvenc
    kind: str            # nvenc | qsv | vaapi | amf | videotoolbox | software
    codec: str           # h264 | hevc | av1
    note: str = ""


# preference order per (gpu_vendor, codec) -> list of (encoder, kind)
def _sw_encoder(si: SystemInfo, codec: str) -> str:
    """Real-time-capable software encoder for live capture.

    For AV1 prefer SVT-AV1 (real-time at low presets); never libaom-av1 (far below
    real-time for a live source) — fall back to libx264 if SVT-AV1 is unavailable.
    """
    if codec == "av1":
        if "libsvtav1" in si.encoders:
            return "libsvtav1"
        return "libx264"
    return {"h264": "libx264", "hevc": "libx265"}.get(codec, "libx264")


def _candidate_encoders(si: SystemInfo, codec: str) -> list[tuple[str, str]]:
    v = si.gpu_vendor
    c = codec
    table: list[tuple[str, str]] = []
    if v == "nvidia":
        table = [(f"{c}_nvenc", "nvenc")]
    elif v == "apple":
        table = [(f"{c}_videotoolbox", "videotoolbox")]
    elif v == "intel":
        if si.os == "windows":
            table = [(f"{c}_qsv", "qsv")]
        else:
            table = [(f"{c}_qsv", "qsv"), (f"{c}_vaapi", "vaapi")]
    elif v == "amd":
        if si.os == "windows":
            table = [(f"{c}_amf", "amf")]
        else:
            table = [(f"{c}_vaapi", "vaapi")]
    # universal fallbacks
    if si.os == "macos":
        table.append((f"{c}_videotoolbox", "videotoolbox"))
    elif si.os == "linux":
        table.append((f"{c}_vaapi", "vaapi"))
    table.append((_sw_encoder(si, c), "software"))
    return table


def choose_encoder(si: SystemInfo, codec: str = "h264", force_software: bool = False,
                   backend: str = "auto") -> EncoderChoice:
    """Pick the video encoder. backend: auto | gpu | cpu (force_software == cpu)."""
    codec = codec.lower()
    if force_software:
        backend = "cpu"
    sw_name = _sw_encoder(si, codec)

    if backend == "cpu":
        if sw_name not in si.encoders:
            die(f"Software encoder {sw_name} not available in this FFmpeg build.")
        note = "CPU / software encoding (user-selected)"
        if codec == "av1" and sw_name == "libx264":
            note = "AV1 software is not real-time; using libx264 (CPU)"
        return EncoderChoice(sw_name, "software", codec, note)

    # gpu or auto: walk the hardware-first candidate list
    for enc, kind in _candidate_encoders(si, codec):
        if enc in si.encoders:
            if backend == "gpu" and kind == "software":
                break  # don't silently fall back to CPU when GPU was requested
            note = "hardware accelerated" if kind != "software" else "software (no HW encoder available)"
            return EncoderChoice(enc, kind, codec, note)
    if backend == "gpu":
        warn(f"No hardware {codec} encoder available — falling back to CPU ({sw_name}).")
        if sw_name in si.encoders:
            return EncoderChoice(sw_name, "software", codec, "software (no GPU encoder available)")
    die(f"No usable encoder for codec {codec} in this FFmpeg build.")


# ---------------------------------------------------------------------------
# Quality presets -> encoder-specific arguments
# ---------------------------------------------------------------------------
QUALITY_LEVELS = ("best", "high", "balanced", "compact")

# Output resolution presets ("native" = capture size, no scaling). Upscaling to
# 4k is deliberate and useful: platforms like YouTube pick their quality tier
# (and bitrate budget) from the uploaded resolution, so a 4K upload gets the
# high-bitrate 4K pipeline even when the source screen is 1080p/1200p.
RESOLUTIONS = ("native", "720p", "1080p", "1440p", "4k")
_RES_DIMS = {"720p": (1280, 720), "1080p": (1920, 1080),
             "1440p": (2560, 1440), "4k": (3840, 2160)}


def _scale_chain(resolution: str) -> Optional[str]:
    """ffmpeg filter scaling to the chosen output resolution, or None for native.

    Fits the capture inside the target (lanczos, aspect preserved) and pads to the
    exact WxH with black bars, so the output is always the standard frame size.
    """
    dims = _RES_DIMS.get((resolution or "native").lower())
    if not dims:
        return None
    w, h = dims
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")


# ---- Live streaming (OBS-style, YouTube RTMP ingest) ------------------------
YOUTUBE_INGEST = "rtmps://a.rtmps.youtube.com:443/live2"


def _stream_target(url: str, key: str) -> str:
    return (url or YOUTUBE_INGEST).rstrip("/") + "/" + key.strip()


def _mask_secret(text: str, secret: Optional[str]) -> str:
    """Redact a credential (stream key) anywhere it appears in display text."""
    if secret:
        return text.replace(secret, "••••••••")
    return text


def _stream_bitrate_k(w: int, h: int, fps: int) -> int:
    """H.264 live bitrate (kbps) per YouTube's recommendations for the frame size."""
    if h <= 720:
        base = 4000
    elif h <= 1080:
        base = 6800
    elif h <= 1440:
        base = 13000
    else:
        base = 23000
    return int(base * 1.5) if fps >= 48 else base


def _stream_encoder_args(enc: EncoderChoice, bitrate_k: int, fps: int) -> list[str]:
    """CBR-ish, low-latency H.264 args for RTMP(S) live ingest (YouTube etc.).

    Live streaming wants a bounded, roughly-constant bitrate (not CRF) and a
    ~2 s keyframe interval, so the platform can segment and adapt.
    """
    br, mx, buf = f"{bitrate_k}k", f"{int(bitrate_k * 1.07)}k", f"{bitrate_k * 2}k"
    gop = ["-g", str(fps * 2), "-keyint_min", str(fps), "-pix_fmt", "yuv420p"]
    a = ["-c:v", enc.name]
    if enc.kind == "nvenc":
        a += ["-preset", "p5", "-tune", "ll", "-rc", "cbr", "-b:v", br,
              "-maxrate", mx, "-bufsize", buf, "-profile:v", "high", "-bf", "0"]
    elif enc.kind == "qsv":
        a += ["-preset", "fast", "-b:v", br, "-maxrate", mx, "-bufsize", buf]
    elif enc.kind == "vaapi":
        a += ["-rc_mode", "CBR", "-b:v", br, "-maxrate", mx, "-profile:v", "high"]
    elif enc.kind == "amf":
        a += ["-usage", "lowlatency", "-rc", "cbr", "-b:v", br, "-maxrate", mx]
    elif enc.kind == "videotoolbox":
        a += ["-b:v", br, "-maxrate", mx, "-realtime", "1"]
    else:  # software libx264
        a += ["-preset", "veryfast", "-tune", "zerolatency", "-b:v", br,
              "-maxrate", mx, "-bufsize", buf, "-profile:v", "high"]
    return a + gop


def _capture_dims(si: SystemInfo, spec: RecordSpec) -> Optional[tuple[int, int]]:
    """Best-effort capture WxH from the selected region/output/screen."""
    if spec.wl_geometry:
        m = re.match(r"\d+,\d+ (\d+)x(\d+)$", spec.wl_geometry)
        if m:
            return int(m.group(1)), int(m.group(2))
    wl_out = spec.wl_output or si.wl_default_output   # native full screen == focused output
    if wl_out:
        for t in si.wl_outputs:
            if t.output == wl_out:
                g = _parse_wxhxy(t.geometry or "")
                if g:
                    return g[0], g[1]
    for geom in (spec.geometry, spec.region):
        g = _parse_wxhxy(geom or "")
        if g:
            return g[0], g[1]
    m = re.match(r"(\d+)x(\d+)$", si.screen or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def _output_dims(si: SystemInfo, spec: RecordSpec) -> Optional[tuple[int, int]]:
    return _RES_DIMS.get((spec.resolution or "native").lower()) or _capture_dims(si, spec)


def _pixrate_mp(si: SystemInfo, spec: RecordSpec) -> Optional[float]:
    """Output pixel throughput in megapixels/second (None if size is unknown)."""
    dims = _output_dims(si, spec)
    if not dims:
        return None
    return dims[0] * dims[1] * spec.fps / 1e6


def _quality_index(q: str) -> int:
    return {"best": 0, "high": 1, "balanced": 2, "compact": 3}.get(q, 0)


def _speed_tier(pixrate: Optional[float]) -> int:
    """Encoder speed tier 0(slowest/best-quality) .. 3(fastest) from the output
    pixel throughput (megapixels/sec). Chosen so the slowest tier still sustains
    real-time capture on typical modern hardware, measured empirically:
      0: <= ~65 MP/s (1080p30, 720p60) — lots of headroom, use best presets
      1: <= ~130 MP/s (1080p60 / 1440p30)
      2: <= ~260 MP/s (4K30 / 1440p60)
      3: > 260 MP/s (4K48+), or unknown-and-large
    Thresholds sit just above each canonical resolution's exact pixel rate
    (1080p30=62.2, 1080p60=124.4, 4K30=248.8 MP/s) so the headline resolutions
    land in the quality tier the presets are designed for, not one notch faster.
    """
    if pixrate is None:
        return 2          # unknown: stay conservative (fast)
    if pixrate <= 65:
        return 0
    if pixrate <= 130:
        return 1
    if pixrate <= 260:
        return 2
    return 3


def encoder_args(enc: EncoderChoice, quality: str,
                 pixrate: Optional[float] = None) -> list[str]:
    """Real-time-capable, quality-first parameters for the chosen encoder.

    Screen capture is a LIVE source: the encoder must keep up with wall-clock
    or frames pile up and get dropped, producing choppy / slowed-down video.
    These presets are tuned to sustain real-time at high resolution/fps while
    staying visually excellent; combined with '-fps_mode cfr' on the output
    (added in build_command) the playback speed is always correct.
    """
    qi = _quality_index(quality)
    # Speed tier from the actual pixel throughput: at low resolutions there is
    # lots of spare encoder time, so use much slower/higher-quality presets;
    # only fall back to fast presets at 4K / high-fps. 'balanced'/'compact' also
    # nudge one tier faster (smaller/cheaper). Everything still sustains realtime.
    st = _speed_tier(pixrate)
    if qi >= 2:
        st = min(3, st + 1)
    a: list[str] = ["-c:v", enc.name]
    if enc.kind == "nvenc":
        # p1(fastest)..p7(slowest). p7 + temporal-AQ + look-ahead is real-time at
        # 1080p and looks superb; drop the preset and the buffering extras as the
        # pixel rate climbs so 4K/high-fps still keeps up.
        preset = ["p7", "p7", "p6", "p5"][st]
        cq = [18, 21, 24, 28][qi]
        a += ["-preset", preset, "-tune", "hq", "-rc", "vbr",
              "-cq", str(cq), "-b:v", "0", "-spatial-aq", "1", "-bf", "3"]
        if st <= 1:            # enough headroom for the quality-boosting extras
            a += ["-temporal-aq", "1", "-rc-lookahead", "20"]
        if enc.codec in ("h264", "hevc"):
            a += ["-profile:v", "high" if enc.codec == "h264" else "main"]
    elif enc.kind == "qsv":
        preset = ["slow", "medium", "fast", "veryfast"][st]
        gq = [19, 22, 26, 30][qi]
        a += ["-preset", preset, "-global_quality", str(gq)]
    elif enc.kind == "vaapi":
        qp = [19, 23, 26, 30][qi]
        a += ["-qp", str(qp)]
        if enc.codec == "h264":
            a += ["-profile:v", "high"]
    elif enc.kind == "amf":
        usage = ["quality", "balanced", "balanced", "speed"][st]
        qp = [19, 23, 26, 30][qi]
        a += ["-quality", usage, "-rc", "cqp", "-qp_i", str(qp), "-qp_p", str(qp)]
    elif enc.kind == "videotoolbox":
        vq = [72, 62, 50, 38][qi]
        a += ["-q:v", str(vq), "-realtime", "1"]
        if enc.codec == "hevc":
            a += ["-tag:v", "hvc1"]
    else:  # software libx264 / libx265 / libsvtav1
        if enc.name == "libsvtav1":
            # SVT-AV1 presets 0(slow)..13(fastest); scale with the pixel rate.
            a += ["-preset", str([6, 8, 9, 11][st]), "-crf", str([26, 29, 32, 35][qi])]
        elif enc.name == "libaom-av1":
            a += ["-crf", str([28, 30, 32, 35][qi]), "-b:v", "0",
                  "-cpu-used", str([6, 7, 8, 8][st]), "-row-mt", "1", "-usage", "realtime"]
        elif enc.name == "libx265":
            a += ["-preset", ["medium", "fast", "faster", "veryfast"][st],
                  "-crf", str([19, 21, 24, 27][qi])]
        else:  # libx264
            a += ["-preset", ["slow", "medium", "fast", "veryfast"][st],
                  "-crf", str([17, 19, 22, 25][qi]), "-profile:v", "high"]
    return a


# ---------------------------------------------------------------------------
# Pixel format / hwupload glue
# ---------------------------------------------------------------------------
def video_filter_for(enc: EncoderChoice) -> Optional[str]:
    if enc.kind == "vaapi":
        return "format=nv12,hwupload"
    if enc.kind == "qsv":
        return "format=nv12,hwupload=extra_hw_frames=64"
    if enc.kind == "software":
        return "format=yuv420p"
    # nvenc / videotoolbox / amf accept yuv420p directly via auto-conversion
    return "format=yuv420p" if enc.kind in ("nvenc", "amf", "videotoolbox") else None


# ---------------------------------------------------------------------------
# Capture input arguments (screen) per platform
# ---------------------------------------------------------------------------
def _parse_geometry(geom: Optional[str]) -> tuple[Optional[str], int, int]:
    """Parse 'WxH+X+Y' (or 'WxH') -> (size 'WxH' or None, x, y)."""
    if not geom:
        return None, 0, 0
    m = re.match(r"(\d+x\d+)(?:\+(\d+)\+(\d+))?$", geom.strip())
    if not m:
        return None, 0, 0
    return m.group(1), int(m.group(2) or 0), int(m.group(3) or 0)


def screen_input_args(si: SystemInfo, fps: int, geometry: Optional[str], enc: EncoderChoice,
                      win_title: Optional[str] = None) -> tuple[list[str], list[str]]:
    """Return (pre_input_args, input_args).

    geometry: 'WxH+X+Y' region of the desktop (a monitor, window rect, or custom
    region). None => full screen. win_title: native window capture (Windows).
    """
    pre: list[str] = []
    inp: list[str] = []
    if enc.kind == "vaapi" and si.vaapi_device:
        pre += ["-vaapi_device", si.vaapi_device]
    if enc.kind == "qsv":
        pre += ["-init_hw_device", "qsv=hw", "-filter_hw_device", "hw"]

    if si.os == "linux":
        if si.display_server == "wayland":
            warn("Wayland session detected: x11grab only sees XWayland windows. "
                 "For full-desktop Wayland capture install 'wf-recorder' or use a kmsgrab setup.")
        size, ox, oy = _parse_geometry(geometry)
        if not size:
            size = si.screen or None
        inp += ["-f", "x11grab", "-framerate", str(fps), "-thread_queue_size", "1024"]
        if size:
            inp += ["-video_size", size]
        display = os.environ.get("DISPLAY", ":0.0")
        inp += ["-i", f"{display}+{ox},{oy}"]
    elif si.os == "macos":
        # avfoundation captures a whole display by index; geometry => screen index.
        screen_idx = (geometry or "1").split("x")[0] if geometry and "x" not in geometry else (geometry or "1")
        inp += ["-f", "avfoundation", "-framerate", str(fps),
                "-capture_cursor", "1", "-i", f"{screen_idx}:none"]
    elif si.os == "windows":
        inp += ["-f", "gdigrab", "-framerate", str(fps), "-thread_queue_size", "1024"]
        if win_title:
            inp += ["-i", f"title={win_title}"]           # native window capture
        else:
            size, ox, oy = _parse_geometry(geometry)
            if size:
                w, h = size.split("x")
                inp += ["-offset_x", str(ox), "-offset_y", str(oy),
                        "-video_size", size]
            inp += ["-i", "desktop"]
    return pre, inp


# ---------------------------------------------------------------------------
# Audio input arguments per platform
# ---------------------------------------------------------------------------
def audio_input_args(si: SystemInfo, dev: AudioDevice) -> list[str]:
    if si.os == "linux":
        return ["-f", "pulse", "-thread_queue_size", "1024", "-i", dev.id]
    if si.os == "macos":
        return ["-f", "avfoundation", "-thread_queue_size", "1024", "-i", f"none:{dev.id}"]
    if si.os == "windows":
        return ["-f", "dshow", "-thread_queue_size", "1024", "-i", f"audio={dev.id}"]
    return []


# ---------------------------------------------------------------------------
# Filename
# ---------------------------------------------------------------------------
def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def ensure_dir(path: str) -> None:
    if os.path.exists(path) and not os.path.isdir(path):
        die(f"Not a directory: {path}")
    os.makedirs(path, exist_ok=True)


# ---------------------------------------------------------------------------
# Build the full ffmpeg command
# ---------------------------------------------------------------------------
@dataclass
class RecordSpec:
    mode: str            # video_both|video_mic|video_system|video_only|audio_mic|audio_system|audio_both
    quality: str = "best"
    codec: str = "h264"
    fps: int = 60
    resolution: str = "native"  # native | 720p | 1080p | 1440p | 4k (scale output)
    region: Optional[str] = None
    out_dir: str = ""
    audio_rate: int = 48000
    audio_codec: str = "flac"   # flac (lossless) | aac | opus
    audio_channels: str = "stereo"  # stereo | mono | left | right (clone a channel to both)
    mic: Optional[AudioDevice] = None
    monitor: Optional[AudioDevice] = None
    force_software: bool = False
    backend: str = "auto"              # auto | gpu | cpu
    container: str = "mkv"
    duration: Optional[float] = None   # stop after N seconds (ffmpeg -t)
    geometry: Optional[str] = None     # capture region "WxH+X+Y" (full screen if None)
    win_title: Optional[str] = None    # Windows gdigrab window title (window capture)
    wl_output: Optional[str] = None    # Wayland output name (wf-recorder -o)
    wl_geometry: Optional[str] = None  # Wayland output-local region "X,Y WxH"
    stream_url: Optional[str] = None   # full RTMP(S) target (ingest URL + key) => go live
    stream_secret: Optional[str] = None  # the stream key, used only to mask displays


def _audio_encode_args(spec: RecordSpec) -> list[str]:
    if spec.audio_codec == "flac":
        return ["-c:a", "flac", "-ar", str(spec.audio_rate), "-ac", "2"]
    if spec.audio_codec == "opus":
        return ["-c:a", "libopus", "-b:a", "256k", "-ar", "48000", "-ac", "2"]
    return ["-c:a", "aac", "-b:a", "320k", "-ar", str(spec.audio_rate), "-ac", "2"]


def _audio_pan(channels: str) -> Optional[str]:
    """ffmpeg pan for channel handling — fixes 'sound only on one side'.

    left / right clone that channel to BOTH outputs (full level — ideal for a mono
    mic wired to one input, e.g. a Focusrite). mono averages both channels onto
    both outputs (clip-safe). stereo keeps the source as-is.
    """
    if channels == "left":
        return "pan=stereo|c0=c0|c1=c0"
    if channels == "right":
        return "pan=stereo|c0=c1|c1=c1"
    if channels == "mono":
        return "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1"
    return None


def _audio_src_filter(spec: RecordSpec) -> str:
    """Per-source audio filter chain: resample (soxr) + channel handling → stereo."""
    pan = _audio_pan(spec.audio_channels)
    chain = f"aresample={spec.audio_rate}:resampler=soxr"
    return chain + (f",{pan}" if pan else ",aformat=channel_layouts=stereo")


def build_command(si: SystemInfo, spec: RecordSpec) -> tuple[list[str], str]:
    is_video = spec.mode.startswith("video")
    wants_mic = spec.mode in ("video_both", "video_mic", "audio_mic", "audio_both")
    wants_sys = spec.mode in ("video_both", "video_system", "audio_system", "audio_both")

    if wants_mic and not spec.mic:
        die("Microphone requested but no microphone device detected/selected.")
    if wants_sys and not spec.monitor:
        die("System audio requested but no monitor/loopback source detected/selected.")

    out_dir = spec.out_dir or (os.path.join(os.path.expanduser("~"), "Videos" if is_video else "Audio"))
    if not spec.stream_url:
        ensure_dir(out_dir)

    cmd: list[str] = [si.ffmpeg, "-y", "-hide_banner", "-loglevel", "info", "-stats"]

    enc = None
    audio_inputs: list[AudioDevice] = []

    if is_video:
        # RTMP ingests want H.264; force it for streaming regardless of --codec.
        enc = choose_encoder(si, "h264" if spec.stream_url else spec.codec,
                             spec.force_software, spec.backend)
        geometry = spec.geometry or spec.region
        pre, vin = screen_input_args(si, spec.fps, geometry, enc, spec.win_title)
        cmd += pre + vin

    # On macOS the screen+audio can come from one avfoundation device, but we
    # keep audio as separate inputs for portability and per-source control.
    if wants_sys:
        audio_inputs.append(spec.monitor)  # type: ignore[arg-type]
    if wants_mic:
        audio_inputs.append(spec.mic)      # type: ignore[arg-type]
    for dev in audio_inputs:
        cmd += audio_input_args(si, dev)
    # YouTube etc. require an audio track; add silence for a video-only stream.
    silent = bool(spec.stream_url) and not audio_inputs
    if silent:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]

    # ---- filtergraph & mapping ----
    video_index = 0 if is_video else None
    audio_start = 1 if is_video else 0

    filtergraph_parts: list[str] = []
    maps: list[str] = []

    if is_video:
        vf = video_filter_for(enc)  # type: ignore[arg-type]
        # Output-resolution scaling runs in software BEFORE any hwupload, so it
        # works identically for software, NVENC, and VAAPI/QSV encoders.
        sc = _scale_chain(spec.resolution)
        if sc:
            vf = f"{sc},{vf}" if vf else sc
        if vf:
            filtergraph_parts.append(f"[{video_index}:v]{vf}[v]")
            maps += ["-map", "[v]"]
        else:
            maps += ["-map", f"{video_index}:v"]

    if silent:
        maps += ["-map", f"{audio_start}:a"]
    if audio_inputs:
        labels = []
        for i, _dev in enumerate(audio_inputs):
            ai = audio_start + i
            lbl = f"a{i}"
            filtergraph_parts.append(f"[{ai}:a]{_audio_src_filter(spec)}[{lbl}]")
            labels.append(f"[{lbl}]")
        if len(labels) == 1:
            maps += ["-map", labels[0]]
            audio_out_label = labels[0]
        else:
            mix = "".join(labels) + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=2:normalize=0[aout]"
            filtergraph_parts.append(mix)
            maps += ["-map", "[aout]"]

    if filtergraph_parts:
        cmd += ["-filter_complex", ";".join(filtergraph_parts)]
    cmd += maps

    streaming = bool(spec.stream_url)

    # ---- encoders ----
    if is_video:
        if streaming:
            dims = _output_dims(si, spec) or (1920, 1080)
            cmd += _stream_encoder_args(enc, _stream_bitrate_k(*dims, spec.fps), spec.fps)
        else:
            cmd += encoder_args(enc, spec.quality, _pixrate_mp(si, spec))  # type: ignore[arg-type]
        # Force constant frame rate so playback speed is always correct even if
        # the encoder briefly falls behind the live source (no slow-motion).
        cmd += ["-fps_mode", "cfr", "-r", str(spec.fps)]
        # color metadata for fidelity
        cmd += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if audio_inputs or silent:
        # RTMP ingests (YouTube) require AAC, not FLAC.
        cmd += (["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
                if streaming else _audio_encode_args(spec))

    if spec.duration and spec.duration > 0:
        cmd += ["-t", f"{spec.duration:g}"]

    if streaming:
        cmd += ["-f", "flv", spec.stream_url]  # type: ignore[list-item]
        return cmd, spec.stream_url            # type: ignore[return-value]

    container = spec.container if is_video else ("flac" if spec.audio_codec == "flac" else ("opus" if spec.audio_codec == "opus" else "m4a"))
    name = f"{spec.mode}_{timestamp()}.{container}"
    out_path = os.path.join(out_dir, name)
    cmd.append(out_path)
    return cmd, out_path


# ---------------------------------------------------------------------------
# Record plan — a backend-agnostic description of how to record
#   procs:    [(label, argv, stop_method)]   stop_method: "q" (ffmpeg) | "int" (wf-recorder)
#   finalize: optional command run after procs stop (e.g. mux video+audio)
#   cleanup:  temp files to delete when done
#   self_timed: True if a proc self-stops on duration (ffmpeg -t); else the
#               runner enforces duration by stopping the procs.
# ---------------------------------------------------------------------------
@dataclass
class RecordPlan:
    out_path: str
    procs: list = field(default_factory=list)
    finalize: Optional[list] = None
    cleanup: list = field(default_factory=list)
    is_video: bool = True
    self_timed: bool = True
    backend: str = "ffmpeg"      # ffmpeg | wf-recorder | wf-recorder+ffmpeg
    # Wayland mic+system: load a PipeWire combined source before recording so a
    # single wf-recorder process owns both clocks (perfect A/V sync). Tuple is
    # (sink_name, mic_id, monitor_id); module ids are captured at activation.
    pulse_setup: Optional[tuple] = None
    fallback: Optional["RecordPlan"] = None   # used if pulse_setup fails
    is_stream: bool = False           # True when pushing to an RTMP(S) target
    secret: Optional[str] = None      # credential to redact from any display
    fifos: list = field(default_factory=list)  # named pipes to create at start


# ---- Wayland (wlroots) encoder selection for wf-recorder --------------------
def wf_codec(si: SystemInfo, spec: RecordSpec, quiet: bool = False,
             force_software: bool = False) -> tuple[str, list[str], str, str]:
    """Return (codec, [codec params], kind, drm_device) for wf-recorder.

    wf-recorder cannot use NVENC; on NVIDIA it uses software (libx264/x265).
    VAAPI is used only on Intel/AMD when available. Presets adapt to the output
    pixel rate: slower/higher-quality when there's headroom, fast at 4K.
    """
    qi = _quality_index(spec.quality)
    st = _speed_tier(_pixrate_mp(si, spec))
    if qi >= 2:
        st = min(3, st + 1)
    codec = spec.codec
    if not force_software and spec.backend != "cpu" \
            and si.gpu_vendor in ("intel", "amd") and si.vaapi_device:
        venc = {"h264": "h264_vaapi", "hevc": "hevc_vaapi"}.get(codec)
        if venc and venc in si.encoders:
            qp = [19, 23, 26, 30][qi]
            return venc, [f"qp={qp}"], "vaapi", si.vaapi_device
    if spec.backend == "gpu" and si.gpu_vendor == "nvidia" and not quiet:
        warn("wf-recorder cannot use NVENC on Wayland; recording with software x264.")
    if codec == "hevc":
        preset = ["medium", "fast", "faster", "veryfast"][st]
        return "libx265", [f"preset={preset}", f"crf={[19,21,24,27][qi]}"], "software", ""
    if codec == "av1" and not quiet:
        warn("AV1 software encoding is not real-time for live capture; using H.264.")
    preset = ["slow", "medium", "fast", "veryfast"][st]
    return "libx264", [f"preset={preset}", f"crf={[17,19,22,25][qi]}"], "software", ""


def _parse_wxhxy(geom: Optional[str]) -> Optional[tuple[int, int, int, int]]:
    """Parse 'WxH+X+Y' or 'WxH' (offset defaults to 0,0) -> (w,h,x,y)."""
    if not geom:
        return None
    m = re.match(r"(\d+)x(\d+)(?:\+(\d+)\+(\d+))?$", geom.strip())
    if not m:
        return None
    w, h, x, y = m.group(1), m.group(2), m.group(3) or 0, m.group(4) or 0
    return int(w), int(h), int(x), int(y)


def _global_to_output_region(si: SystemInfo, geom: str,
                             prefer: Optional[str] = None) -> tuple[str, Optional[str]]:
    """Map a global 'WxH+X+Y' rect to (output_name, 'X,Y WxH' local to that output)."""
    g = _parse_wxhxy(geom)
    if not g:
        return prefer or si.wl_default_output, None
    w, h, x, y = g
    chosen = None
    for t in si.wl_outputs:
        og = _parse_wxhxy(t.geometry or "")
        if not og:
            continue
        ow, oh, ox, oy = og
        if (prefer and t.output == prefer) or (ox <= x < ox + ow and oy <= y < oy + oh):
            chosen = t
            if not prefer or t.output == prefer:
                break
    if not chosen:
        chosen = next((t for t in si.wl_outputs if t.output == (prefer or si.wl_default_output)),
                      si.wl_outputs[0] if si.wl_outputs else None)
    if not chosen:
        return prefer or si.wl_default_output, f"{x},{y} {w}x{h}"
    cw, ch, ox, oy = _parse_wxhxy(chosen.geometry or "") or (0, 0, 0, 0)
    lx, ly = max(0, x - ox), max(0, y - oy)
    # clamp the region so it never exceeds the output bounds
    rw = min(w, cw - lx) if cw else w
    rh = min(h, ch - ly) if ch else h
    return chosen.output or "", f"{lx},{ly} {max(1, rw)}x{max(1, rh)}"


def _pulse_mix_load(sink_name: str, mic_id: str, monitor_id: str) -> Optional[list[str]]:
    """Create a PipeWire/Pulse combined source mixing mic + system audio.

    Loads a null sink and loops the mic and the system monitor into it, so its
    .monitor is one source carrying both — letting a single wf-recorder process
    capture perfectly A/V-synced video + mixed audio. Returns the loaded module
    ids (to unload later), or None if the modules could not be created.
    """
    if not shutil.which("pactl"):
        return None

    def load(args: list[str]) -> Optional[str]:
        out = run_cmd(["pactl", "load-module"] + args).strip()
        last = out.splitlines()[-1].strip() if out else ""
        return last if last.isdigit() else None

    ids: list[str] = []
    sink = load(["module-null-sink", f"sink_name={sink_name}",
                 f"sink_properties=device.description={sink_name}"])
    if not sink:
        return None
    ids.append(sink)
    for src in (mic_id, monitor_id):
        m = load(["module-loopback", f"source={src}", f"sink={sink_name}", "latency_msec=30"])
        if not m:
            _pulse_mix_unload(ids)
            return None
        ids.append(m)
    return ids


def _pulse_mix_unload(ids: list[str]) -> None:
    for m in reversed(ids or []):
        run_cmd(["pactl", "unload-module", m])


def _activate_plan(plan: "RecordPlan") -> tuple["RecordPlan", list[str]]:
    """Perform a plan's pre-record setup (FIFOs + PipeWire mix). Returns (plan, module ids)."""
    for fifo in plan.fifos:
        try:
            os.path.exists(fifo) or os.mkfifo(fifo)
        except OSError as e:
            die(f"Could not create stream pipe {fifo}: {e}")
    if plan.pulse_setup:
        sink, mic_id, mon_id = plan.pulse_setup
        ids = _pulse_mix_load(sink, mic_id, mon_id)
        if ids:
            return plan, ids
        warn("Could not create a combined mic+system source; "
             "falling back to a separate audio recorder (A/V sync may drift slightly).")
        if plan.fallback:
            return plan.fallback, []
    return plan, []


def _plan_cleanup(plan: "RecordPlan") -> None:
    """Remove a plan's temp files and directories (FIFOs, scratch dirs)."""
    for path in plan.cleanup:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def _redact_cmd(argv: list, secret: Optional[str]) -> str:
    return _mask_secret(" ".join(_shquote(c) for c in argv), secret)


def _pump_masked_stderr(stream, secret: Optional[str]) -> None:
    """Forward a child's stderr to ours with `secret` masked. ffmpeg prints the
    output URL (which for a stream contains the key) at info level, and error
    lines echo it even at error level; without this the key would appear in
    cleartext in the terminal/scrollback/redirected logs, defeating the
    redaction applied to everything the app prints itself. We split on both '\\n'
    and '\\r' (so '-stats' progress still renders live) and only ever emit whole
    lines, so the secret — always contained within one line — is fully present
    when _mask_secret runs and can never be split across a read boundary."""
    buf = ""
    try:
        while True:
            chunk = stream.read(256)
            if not chunk:
                break
            buf += chunk.decode("utf-8", "replace")
            parts = re.split(r"([\r\n])", buf)
            buf = parts[-1]                 # keep the trailing incomplete segment
            done = "".join(parts[:-1])
            if done:
                sys.stderr.write(_mask_secret(done, secret))
                sys.stderr.flush()
        if buf:
            sys.stderr.write(_mask_secret(buf, secret))
            sys.stderr.flush()
    except Exception:
        pass


def _ffmpeg_audio_cmd(si: SystemInfo, spec: RecordSpec, devices: list, out_path: str) -> list[str]:
    """ffmpeg command capturing one or more audio sources (mixed) to out_path,
    applying the channel handling (--audio-channels) via _audio_src_filter."""
    cmd = [si.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-stats"]
    for dev in devices:
        cmd += audio_input_args(si, dev)
    parts, labels = [], []
    for i in range(len(devices)):
        parts.append(f"[{i}:a]{_audio_src_filter(spec)}[a{i}]")
        labels.append(f"[a{i}]")
    if len(labels) == 1:
        out_label = labels[0]
    else:
        parts.append("".join(labels)
                     + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=2:normalize=0[aout]")
        out_label = "[aout]"
    cmd += ["-filter_complex", ";".join(parts), "-map", out_label]
    cmd += _audio_encode_args(spec)
    cmd.append(out_path)
    return cmd


def _ffmpeg_stream_mux_cmd(si: SystemInfo, spec: RecordSpec, fifo: str, devices: list) -> list[str]:
    """ffmpeg that reads the wf-recorder H.264 mpegts FIFO (video stream-copy),
    captures + mixes the audio to AAC, and pushes FLV to the RTMP(S) target."""
    cmd = [si.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-stats",
           "-thread_queue_size", "1024", "-fflags", "+genpts", "-i", fifo]
    if devices:
        for dev in devices:
            cmd += audio_input_args(si, dev)
        parts, labels = [], []
        for i in range(len(devices)):
            parts.append(f"[{i + 1}:a]{_audio_src_filter(spec)}[a{i}]")
            labels.append(f"[a{i}]")
        if len(labels) == 1:
            out_label = labels[0]
        else:
            parts.append("".join(labels)
                         + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=2:normalize=0[aout]")
            out_label = "[aout]"
        cmd += ["-filter_complex", ";".join(parts), "-map", "0:v:0", "-map", out_label]
    else:  # video-only stream: YouTube still needs an audio track
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-f", "flv", spec.stream_url]  # type: ignore[list-item]
    return cmd


def _build_wayland_plan(si: SystemInfo, spec: RecordSpec, preview: bool,
                        out_dir: str, wants_mic: bool, wants_sys: bool) -> RecordPlan:
    if not si.wayland_recorder:
        die("Wayland session detected but 'wf-recorder' is not installed — it is "
            "required to capture a wlroots (sway/Hyprland/river) desktop.\n"
            "  Install:  guix install wf-recorder  ·  sudo apt install wf-recorder  ·  "
            "sudo dnf install wf-recorder")
    wf = si.wayland_recorder
    # resolve output + output-local geometry
    output = spec.wl_output or si.wl_default_output
    wl_geom = spec.wl_geometry
    if not output and si.wl_outputs:
        output = si.wl_outputs[0].output or ""
    if not output:
        die("No Wayland output detected to record. Run 'turborec targets' to list "
            "outputs, then pass --monitor <name> (or check that swaymsg/wlr-randr works).")
    codec, cparams, kind, drm = wf_codec(si, spec, quiet=preview)
    # Output-resolution scaling (wf-recorder -F runs an ffmpeg filter chain).
    # The software scale chain can't feed a VAAPI encoder's hw frames, so when
    # scaling is requested on a VAAPI pick, drop to the software encoder.
    scale = _scale_chain(spec.resolution)
    if scale and kind == "vaapi":
        if not preview:
            warn("Scaled output resolution is not supported with VAAPI on Wayland; "
                 "using the software encoder for this recording.")
        codec, cparams, kind, drm = wf_codec(si, spec, quiet=True, force_software=True)
    container = spec.container or "mkv"
    ts = timestamp()
    out_path = os.path.join(out_dir, f"{spec.mode}_{ts}.{container}")

    acodec = {"flac": "flac", "aac": "aac", "opus": "libopus"}.get(spec.audio_codec, "flac")

    def wf_cmd(target_file: str, audio_dev: Optional[str] = "__none__") -> list[str]:
        c = [wf, "-o", output, "-c", codec, "-r", str(spec.fps), "-x", "yuv420p"]
        for p in cparams:
            c += ["-p", p]
        if kind == "vaapi" and drm:
            c += ["-d", drm]
        if wl_geom:
            c += ["-g", wl_geom]
        if scale:
            c += ["-F", scale]       # wf-recorder appends fps=N to this chain itself
        if audio_dev != "__none__":
            c += [f"--audio={audio_dev}"] if audio_dev else ["--audio"]
            c += ["-C", acodec]      # honor the chosen audio codec (flac/aac/opus)
        c += ["-f", target_file]
        return c

    # ---- Live streaming on Wayland ----
    # wf-recorder can't mix mic+system or emit AAC, so it encodes H.264 into an
    # mpegts FIFO which ffmpeg reads (stream-copy) while it captures + mixes the
    # audio (AAC) and pushes the FLV to the RTMP(S) target.
    if spec.stream_url:
        dims = _output_dims(si, spec) or (1920, 1080)
        br = _stream_bitrate_k(*dims, spec.fps)
        # Only mint a real temp dir + FIFO when we will actually record; the live
        # GUI preview and CLI --dry-run rebuild this plan repeatedly and would
        # otherwise orphan a turborec-stream.* dir on every rebuild.
        fdir = None if preview else tempfile.mkdtemp(prefix="turborec-stream.")
        fifo = os.path.join(fdir, "v.ts") if fdir else "<stream-pipe>"
        vcmd = [wf, "-o", output, "-D", "-c", "libx264", "-r", str(spec.fps), "-x", "yuv420p",
                "-p", "preset=veryfast", "-p", "tune=zerolatency",
                "-p", f"b={br * 1000}", "-p", f"maxrate={int(br * 1070)}",
                "-p", f"bufsize={br * 2000}", "-p", f"g={spec.fps * 2}"]
        if wl_geom:
            vcmd += ["-g", wl_geom]
        if scale:
            vcmd += ["-F", scale]
        vcmd += ["-m", "mpegts", "-f", fifo]
        devices = ([spec.monitor] if wants_sys else []) + ([spec.mic] if wants_mic else [])
        muxcmd = _ffmpeg_stream_mux_cmd(si, spec, fifo, devices)
        return RecordPlan(
            spec.stream_url,
            [("wf-recorder (video → stream)", vcmd, "int"),
             ("ffmpeg (audio + RTMP push)", muxcmd, "int")],
            self_timed=False, backend="wf-recorder+ffmpeg",
            is_stream=True, secret=spec.stream_secret,
            fifos=([fifo] if fdir else []), cleanup=([fdir] if fdir else []))

    if not (wants_mic or wants_sys):
        return RecordPlan(out_path, [("wf-recorder", wf_cmd(out_path), "int")],
                          self_timed=False, backend="wf-recorder")

    # wf-recorder captures audio verbatim and can't remap channels, so when the
    # user asks for channel handling (mono/left/right clone), route audio through
    # ffmpeg (which applies the pan) and mux it with the wf-recorder video.
    def ffmpeg_audio_plan(devices: list) -> RecordPlan:
        # Scratch/mux files go in a fresh private 0700 dir (not the user-chosen
        # out_dir), so their predictable names can't be pre-planted as symlinks
        # when out_dir is shared. Skip the mkdtemp for preview/dry-run builds so
        # repeated GUI rebuilds don't orphan temp dirs (same guard as streaming).
        sdir = out_dir if preview else tempfile.mkdtemp(prefix="turborec-mux.")
        atmp = os.path.join(sdir, f"audio.{_audio_ext(spec)}")
        vtmp = os.path.join(sdir, "video.mkv")
        mux = [si.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
               "-i", vtmp, "-i", atmp, "-map", "0:v:0", "-map", "1:a:0",
               "-c", "copy", out_path]
        return RecordPlan(
            out_path,
            [("wf-recorder (video)", wf_cmd(vtmp), "int"),
             ("ffmpeg (audio)", _ffmpeg_audio_cmd(si, spec, devices, atmp), "q")],
            finalize=mux, cleanup=[vtmp, atmp] + ([] if preview else [sdir]),
            self_timed=False, backend="wf-recorder+ffmpeg")

    devices = ([spec.monitor] if wants_sys else []) + ([spec.mic] if wants_mic else [])
    if _audio_pan(spec.audio_channels):
        return ffmpeg_audio_plan(devices)

    if wants_mic and wants_sys:
        # PRIMARY: one PipeWire combined source -> a single wf-recorder process
        # captures perfectly A/V-synced video + mixed (mic+system) audio.
        sink = f"turborec_mix_{ts}".replace("-", "_").replace(":", "_")
        primary = RecordPlan(
            out_path, [("wf-recorder (video+mixed audio)", wf_cmd(out_path, f"{sink}.monitor"), "int")],
            self_timed=False, backend="wf-recorder",
            pulse_setup=(sink, spec.mic.id, spec.monitor.id))  # type: ignore[union-attr]
        primary.fallback = ffmpeg_audio_plan(devices)   # if the combined source fails
        return primary
    dev = spec.monitor.id if wants_sys else spec.mic.id  # type: ignore[union-attr]
    return RecordPlan(out_path, [("wf-recorder", wf_cmd(out_path, dev), "int")],
                      self_timed=False, backend="wf-recorder")


def _audio_ext(spec: RecordSpec) -> str:
    return {"flac": "flac", "opus": "opus", "aac": "m4a"}.get(spec.audio_codec, "flac")


def build_plan(si: SystemInfo, spec: RecordSpec, preview: bool = False) -> RecordPlan:
    """Backend-agnostic recording plan. Wayland video -> wf-recorder; else ffmpeg."""
    is_video = spec.mode.startswith("video")
    wants_mic = spec.mode in ("video_both", "video_mic", "audio_mic", "audio_both")
    wants_sys = spec.mode in ("video_both", "video_system", "audio_system", "audio_both")
    if wants_mic and not spec.mic:
        die("Microphone requested but no microphone device detected/selected.")
    if wants_sys and not spec.monitor:
        die("System audio requested but no monitor/loopback source detected/selected.")
    streaming = bool(spec.stream_url)
    if streaming and not is_video:
        die("Streaming requires a video mode (video_only/mic/system/both).")
    out_dir = spec.out_dir or (os.path.join(os.path.expanduser("~"),
                                            "Videos" if is_video else "Audio"))
    if not preview and not streaming:
        ensure_dir(out_dir)
    if is_video and si.os == "linux" and si.display_server == "wayland":
        return _build_wayland_plan(si, spec, preview, out_dir, wants_mic, wants_sys)
    cmd, out_path = build_command(si, spec)
    return RecordPlan(out_path, [("ffmpeg", cmd, "int" if streaming else "q")],
                      is_video=is_video, self_timed=not streaming, backend="ffmpeg",
                      is_stream=streaming, secret=spec.stream_secret)


# ---------------------------------------------------------------------------
# Recording runner (graceful stop)
# ---------------------------------------------------------------------------
def record_plan(plan: "RecordPlan", dry_run: bool = False, countdown_secs: int = 0,
                open_when_done: bool = False, duration: Optional[float] = None) -> int:
    """Run a RecordPlan: start its process(es), stop them gracefully, finalize."""
    dest = _mask_secret(plan.out_path, plan.secret)
    info(("Streaming → " if plan.is_stream else "Output → ") + bold(dest))
    for label, argv, _m in plan.procs:
        info(f"{label}:")
        print(dim(_redact_cmd(argv, plan.secret)), file=sys.stderr)
    if plan.finalize:
        print(dim("  (then mux) " + _redact_cmd(plan.finalize, plan.secret)), file=sys.stderr)
    if dry_run:
        return 0
    if countdown_secs > 0:
        countdown(countdown_secs)

    # pre-record setup (PipeWire combined source); may switch to a fallback plan
    plan, pulse_ids = _activate_plan(plan)
    if plan.is_stream:
        info(f"{green('● LIVE')} — press {bold('q')} or {bold('Ctrl-C')} to stop streaming.")
        # The RTMP output URL (with the key) is an ffmpeg argv element, so it is
        # visible to other local users via the process list while live. This is
        # inherent to ffmpeg RTMP output; only relevant on shared multi-user hosts.
        dim_note = dim("  note: on a shared machine your stream key is visible to "
                       "other local users via the process list while live.")
        print(dim_note, file=sys.stderr)
    else:
        stop_hint = "stop early" if duration else "stop and finalize"
        info(f"Recording… press {bold('q')} or {bold('Ctrl-C')} to {stop_hint}.")

    running: list[tuple[subprocess.Popen, str]] = []
    try:
        for _label, argv, method in plan.procs:
            stdin = subprocess.PIPE if method == "q" else subprocess.DEVNULL
            # For a live stream, capture the child's stderr and mask the key
            # before echoing it — ffmpeg prints the RTMP URL at info/error level.
            stderr = subprocess.PIPE if (plan.is_stream and plan.secret) else None
            proc = subprocess.Popen(argv, stdin=stdin, stderr=stderr)
            if stderr is not None:
                threading.Thread(target=_pump_masked_stderr,
                                 args=(proc.stderr, plan.secret), daemon=True).start()
            running.append((proc, method))
    except OSError as e:
        for p, m in running:           # don't leak already-started processes
            _stop_proc(p, m)
        _pulse_mix_unload(pulse_ids)
        die(f"Failed to launch recorder: {e}")

    primary = running[0][0]
    try:
        if duration and duration > 0 and not plan.self_timed:
            _wait_with_timeout(primary, duration)
        else:
            primary.wait()
    except KeyboardInterrupt:
        pass
    _stop_all(running)
    _pulse_mix_unload(pulse_ids)

    # a None returncode (un-reaped / killed) is a failure, not success
    rc = max(((p.returncode if p.returncode is not None else 1) for p, _ in running), default=0)
    # A stream we asked to stop exits via SIGINT (255 / -2 / 130) — that's clean.
    if plan.is_stream and rc in (255, 130, -2, -15, -signal.SIGINT if hasattr(signal, "SIGINT") else -2):
        rc = 0
    inputs_ok = all(os.path.exists(t) and os.path.getsize(t) > 0 for t in plan.cleanup)
    if plan.finalize:
        if not inputs_ok:
            warn("recording produced no usable video/audio to mux.")
            rc = rc or 1
        else:
            info("Muxing audio + video…")
            try:
                mux = subprocess.run(plan.finalize, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if mux.returncode != 0:
                    rc = mux.returncode
                    warn("mux failed:\n" + mux.stderr.decode("utf-8", "replace")[-400:])
            except OSError as e:
                rc = 1
                warn(f"mux failed: {e}")
    _plan_cleanup(plan)

    if plan.is_stream:
        info(f"{green('Stream ended.')}") if rc == 0 else warn(f"stream exited with code {rc}")
    elif rc == 0 and os.path.exists(plan.out_path):
        try:
            size = _gui_fmt_size(os.path.getsize(plan.out_path))
        except OSError:
            size = "?"
        info(f"{green('Saved ✓')}  {bold(os.path.basename(plan.out_path))}  ({size})")
        if open_when_done:
            open_file(plan.out_path)
    elif rc != 0:
        warn(f"recording exited with code {rc}")
    return rc


def _wait_with_timeout(proc: subprocess.Popen, seconds: float) -> None:
    """Wait up to `seconds` of wall-clock, returning early if the process exits."""
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            proc.wait(timeout=min(0.25, remaining))
            return
        except subprocess.TimeoutExpired:
            continue


def _reap(proc: subprocess.Popen) -> None:
    """Final wait() so a killed/terminated child is reaped (no zombie)."""
    try:
        proc.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _signal_stop(proc: subprocess.Popen, method: str) -> None:
    """Ask one process to stop (non-blocking): SIGINT, or 'q' on stdin for ffmpeg."""
    if proc.poll() is not None:
        return
    if method == "int":
        if hasattr(signal, "SIGINT"):
            proc.send_signal(signal.SIGINT)
    else:
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.write(b"q")
                proc.stdin.flush()
        except (OSError, ValueError):
            pass


def _stop_all(running: list) -> None:
    """Stop several capture processes together. Signalling every process FIRST
    (before waiting on any) is essential for the FIFO streaming pipeline: the
    wf-recorder writer can be blocked writing to a pipe whose ffmpeg reader must
    also be told to quit — waiting on one before signalling the other deadlocks."""
    for proc, method in running:
        _signal_stop(proc, method)
    for proc, method in running:
        if proc.poll() is not None:
            continue
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            if method != "int" and hasattr(signal, "SIGINT"):
                proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    _reap(proc)


def _stop_proc(proc: subprocess.Popen, method: str) -> None:
    """Stop one recording process and let it finalize its file (then reap it)."""
    if proc.poll() is not None:
        return
    if method != "int":
        _graceful_stop(proc)
        return
    if hasattr(signal, "SIGINT"):
        proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            _reap(proc)


def _graceful_stop(proc: subprocess.Popen) -> None:
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.write(b"q")
            proc.stdin.flush()
    except (OSError, ValueError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if hasattr(signal, "SIGINT"):
            proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                _reap(proc)


def _shquote(s: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:+=@%-]+", s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------
# Countdown · open-when-done · post-record summary
# ---------------------------------------------------------------------------
def countdown(seconds: int) -> None:
    """Print a single-line countdown to stderr before recording starts."""
    if seconds <= 0:
        return
    interactive = sys.stderr.isatty()
    for remaining in range(seconds, 0, -1):
        if interactive:
            print(f"\r{cyan('::')} Starting in {bold(str(remaining))}… ",
                  end="", file=sys.stderr, flush=True)
        else:
            info(f"Starting in {remaining}…")
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            if interactive:
                print(file=sys.stderr)
            raise
    if interactive:
        print("\r" + " " * 28 + "\r", end="", file=sys.stderr, flush=True)


def open_file(path: str) -> None:
    """Open a finished recording with the platform's default handler."""
    if not path or not os.path.exists(path):
        warn(f"Cannot open (file not found): {path}")
        return
    os_name = detect_os()
    try:
        if os_name == "macos":
            subprocess.Popen(["open", path])
        elif os_name == "windows":
            os.startfile(path)  # type: ignore[attr-defined]  # noqa: B606
        elif shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            warn("No 'xdg-open' found to open the file automatically.")
            return
        info(f"Opening {bold(os.path.basename(path))}…")
    except (OSError, AttributeError) as e:
        warn(f"Could not open file: {e}")


# ---------------------------------------------------------------------------
# Machine-readable system report (detect --json)
# ---------------------------------------------------------------------------
def system_info_to_dict(si: SystemInfo) -> dict:
    """Serialize a probe into a stable, scriptable JSON structure."""
    def best(codec: str) -> Optional[dict]:
        try:
            e = choose_encoder(si, codec)
        except SystemExit:
            return None
        return {"encoder": e.name, "kind": e.kind, "note": e.note}

    def dev(d: Optional[AudioDevice]) -> Optional[dict]:
        return asdict(d) if d else None

    return {
        "app": APP_NAME,
        "version": VERSION,
        "os": si.os,
        "display_server": si.display_server,
        "cpu": {"vendor": si.cpu_vendor, "model": si.cpu_model},
        "gpu": {"vendor": si.gpu_vendor, "model": si.gpu_model,
                "present": si.has_gpu, "vaapi_device": si.vaapi_device or None},
        "screen": si.screen or None,
        "ffmpeg": si.ffmpeg,
        "best_encoders": {c: best(c) for c in ("h264", "hevc", "av1")},
        "default_mic": dev(si.default_mic),
        "default_monitor": dev(si.default_monitor),
        "mics": [asdict(m) for m in si.mics],
        "monitors": [asdict(m) for m in si.monitors],
    }


# ---------------------------------------------------------------------------
# Pretty system report
# ---------------------------------------------------------------------------
def print_report(si: SystemInfo) -> None:
    def line(k, v):
        print(f"  {dim(k+':'):<28} {v}")

    print(bold(f"\n{APP_NAME} {VERSION} — system probe\n"))
    line("Operating system", si.os)
    line("Display server", si.display_server)
    line("CPU", f"{si.cpu_vendor}  ({si.cpu_model})")
    gpu = f"{si.gpu_vendor}  ({si.gpu_model})" if si.gpu_model else si.gpu_vendor
    line("GPU", gpu + (green("  [present]") if si.has_gpu else yellow("  [none/SW only]")))
    if si.vaapi_device:
        line("VAAPI device", si.vaapi_device)
    line("Screen", si.screen or "unknown")
    line("FFmpeg", si.ffmpeg)
    print()
    for codec in ("h264", "hevc", "av1"):
        try:
            enc = choose_encoder(si, codec)
            line(f"Best {codec} encoder", f"{green(enc.name)}  ({enc.kind}, {enc.note})")
        except SystemExit:
            line(f"Best {codec} encoder", yellow("unavailable"))
    print()
    if si.default_mic:
        line("Default microphone", si.default_mic.label)
    else:
        line("Default microphone", yellow("none detected"))
    if si.default_monitor:
        line("System audio (loopback)", si.default_monitor.label)
    else:
        line("System audio (loopback)", yellow("none detected"))
    if si.mics:
        print(f"\n  {dim('Microphones:')}")
        for m in si.mics:
            print(f"    - {m.label}")
    if si.monitors:
        print(f"\n  {dim('System-audio sources:')}")
        for m in si.monitors:
            print(f"    - {m.label}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
MODES = (
    "video_both", "video_mic", "video_system", "video_only",
    "audio_both", "audio_mic", "audio_system",
)

# RC keys that may appear under [record] / top level of the config file. Each
# maps to the matching argparse dest; values become argparse defaults so an
# explicit CLI flag always wins.
_RC_KEYS = (
    "mode", "quality", "codec", "fps", "resolution", "stream_url", "out", "region", "audio_rate",
    "audio_codec", "audio_channels", "container", "mic_device", "system_device", "software",
    "duration", "countdown", "open", "quiet", "ffmpeg",
)


def _config_paths() -> list[str]:
    """Candidate RC files, lowest→highest precedence."""
    paths = []
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config")
    paths.append(os.path.join(xdg, "turborec", "config.json"))
    paths.append(os.path.join(os.path.expanduser("~"), ".turborec.json"))
    env = os.environ.get("TURBOREC_CONFIG")
    if env:
        paths.append(env)
    return paths


def load_config(explicit: Optional[str] = None) -> dict:
    """Read JSON RC files and return a flat {dest: value} mapping.

    Searches XDG config, ~/.turborec.json and $TURBOREC_CONFIG (then an
    explicit --config path, highest precedence). Unknown keys are ignored;
    malformed files warn but never abort. A nested {"record": {...}} block is
    flattened so users can scope defaults to the record subcommand.
    """
    merged: dict = {}
    for path in _config_paths() + ([explicit] if explicit else []):
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", errors="replace") as fh:
                data = json.load(fh)
        except (OSError, ValueError, RecursionError) as e:
            # RecursionError: pathologically deep JSON. Honor "warn, never abort".
            warn(f"Ignoring config {path}: {e}")
            continue
        if not isinstance(data, dict):
            continue
        flat = dict(data)
        if isinstance(data.get("record"), dict):
            flat.update(data["record"])
        for k, v in flat.items():
            if k in _RC_KEYS:
                merged[k] = v
    return merged


def parse_duration(text: str) -> float:
    """Parse '90', '90s', '5m', '1h30m', '00:01:30' → seconds (float)."""
    text = text.strip().lower()
    if not text:
        raise argparse.ArgumentTypeError("empty duration")
    if ":" in text:  # HH:MM:SS or MM:SS
        parts = text.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError as e:
            raise argparse.ArgumentTypeError(f"bad time '{text}'") from e
        secs = 0.0
        for n in nums:
            secs = secs * 60 + n
        return secs
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s?)?", text)
    if not m or not any(m.groups()):
        raise argparse.ArgumentTypeError(
            f"bad duration '{text}' (use 90, 90s, 5m, 1h30m or HH:MM:SS)")
    h, mi, s = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def _resolve_audio_devices(si: SystemInfo, args) -> tuple[Optional[AudioDevice], Optional[AudioDevice]]:
    mic = si.default_mic
    mon = si.default_monitor
    if getattr(args, "mic_device", None):
        mic = next((m for m in si.mics if m.id == args.mic_device or m.label == args.mic_device), None)
        if mic is None:
            mic = AudioDevice(id=args.mic_device, label=args.mic_device)
    if getattr(args, "system_device", None):
        mon = next((m for m in si.monitors if m.id == args.system_device or m.label == args.system_device), None)
        if mon is None:
            mon = AudioDevice(id=args.system_device, label=args.system_device, is_monitor=True)
    return mic, mon


def _resolve_backend(args) -> str:
    if getattr(args, "cpu", False) or getattr(args, "software", False):
        return "cpu"
    if getattr(args, "gpu", False):
        return "gpu"
    return getattr(args, "backend", None) or "auto"


def _resolve_capture_target(si: SystemInfo, args) -> Optional[CaptureTarget]:
    """Return the selected CaptureTarget from CLI flags, or None for full screen."""
    if getattr(args, "region", None):
        return CaptureTarget(kind="region", label="region", geometry=args.region)
    targets = detect_capture_targets(si)
    sel = getattr(args, "monitor", None)
    if sel:
        for t in targets:
            if t.kind == "monitor" and (sel.lower() in t.label.lower()
                                        or sel == (t.output or "")):
                return t
        die(f"Monitor '{sel}' not found. Try: turborec targets")
    sel = getattr(args, "window", None)
    if sel:
        for t in targets:
            if t.kind == "window" and (sel == (t.win_title or "") or sel.lower() in t.label.lower()):
                return t
        die(f"Window '{sel}' not found. Try: turborec targets")
    return None


def _target_to_wayland(si: SystemInfo, target: CaptureTarget) -> tuple[str, Optional[str]]:
    """Map a CaptureTarget to (wayland output, output-local 'X,Y WxH' or None)."""
    out = target.output or si.wl_default_output
    if target.kind in ("screen", "monitor"):
        return out, None
    if target.geometry:    # window / region -> output-local region
        return _global_to_output_region(si, target.geometry, prefer=target.output)
    return out, None


def _apply_target_to_spec(si: SystemInfo, target: Optional[CaptureTarget], spec: RecordSpec) -> None:
    if target is None:
        return
    if si.display_server == "wayland":
        spec.wl_output, spec.wl_geometry = _target_to_wayland(si, target)
    else:
        spec.geometry = target.geometry
        spec.win_title = target.win_title


def cmd_record(args) -> int:
    si = probe_system(args.ffmpeg)
    backend = _resolve_backend(args)
    target = _resolve_capture_target(si, args)
    mic, mon = _resolve_audio_devices(si, args)
    # Strip once at the source so the value embedded in the RTMP URL is byte-for-byte
    # the value stored as the redaction secret (a whitespace-padded key would otherwise
    # slip past _mask_secret's literal substring match and print in cleartext).
    key = (getattr(args, "stream", None) or "").strip() or None
    ingest = (getattr(args, "stream_url", None) or "").strip()
    if key and ingest and not ingest.lower().startswith(("rtmp://", "rtmps://")):
        die("--stream-url must be an rtmp:// or rtmps:// ingest URL")
    stream_url = _stream_target(ingest, key) if key else None
    spec = RecordSpec(
        mode=args.mode, quality=args.quality, codec=args.codec, fps=args.fps,
        resolution=args.resolution,
        region=args.region, out_dir=args.out or "", audio_rate=args.audio_rate,
        audio_codec=args.audio_codec, audio_channels=args.audio_channels, mic=mic, monitor=mon,
        force_software=args.software, backend=backend, container=args.container,
        duration=args.duration, stream_url=stream_url, stream_secret=key,
    )
    _apply_target_to_spec(si, target, spec)
    if not args.quiet:
        loc = spec.wl_output or spec.geometry or "full screen"
        info(f"{si.os}/{si.display_server} · CPU {si.cpu_vendor} · GPU {si.gpu_vendor}"
             f"{' (HW)' if si.has_gpu else ' (SW)'} · {si.screen or '?'} · encoder {backend} · {loc}"
             + (" · LIVE" if stream_url else ""))
    # A dry run only prints the plan; build it in preview mode so it never touches
    # the filesystem (no output dir, no stream temp dir / FIFO).
    plan = build_plan(si, spec, preview=args.dry_run)
    return record_plan(plan, dry_run=args.dry_run, countdown_secs=args.countdown,
                       open_when_done=args.open, duration=args.duration)


def cmd_targets(args) -> int:
    """List capture targets (full screen, monitors, windows) — OBS-style."""
    si = probe_system(args.ffmpeg)
    targets = detect_capture_targets(si)
    if getattr(args, "json", False):
        print(json.dumps([asdict(t) for t in targets], indent=2))
        return 0
    print(bold("\nCapture targets"))
    for t in targets:
        tag = {"screen": "screen", "monitor": "monitor", "window": "window"}.get(t.kind, t.kind)
        print(f"  {cyan(f'[{tag}]'):<18} {t.label}  {dim(t.geometry or '')}")
    print(f"\n{dim('Use with:')} turborec record --monitor <name> | "
          f"--window <title> | --region WxH+X+Y")
    return 0


def cmd_detect(args) -> int:
    si = probe_system(args.ffmpeg)
    if getattr(args, "json", False):
        print(json.dumps(system_info_to_dict(si), indent=2))
    else:
        print_report(si)
    return 0


def cmd_devices(args) -> int:
    """List audio devices with indices, ready to paste into --mic-device etc."""
    si = probe_system(args.ffmpeg)
    if getattr(args, "json", False):
        info_dict = {
            "mics": [asdict(m) for m in si.mics],
            "monitors": [asdict(m) for m in si.monitors],
            "default_mic": asdict(si.default_mic) if si.default_mic else None,
            "default_monitor": asdict(si.default_monitor) if si.default_monitor else None,
        }
        print(json.dumps(info_dict, indent=2))
        return 0

    def show(title, devs, default):
        print(bold(f"\n{title}"))
        if not devs:
            print(f"  {yellow('(none detected)')}")
            return
        for i, d in enumerate(devs):
            mark = green(" *") if default and d.id == default.id else "  "
            print(f"{mark}[{cyan(str(i))}] {d.label}")
            if d.label != d.id:
                print(f"     {dim('id: ' + d.id)}")
    show("Microphones", si.mics, si.default_mic)
    show("System-audio sources (monitor/loopback)", si.monitors, si.default_monitor)
    print(f"\n{dim('Use with:')} turborec record --mic-device <id|label> "
          f"--system-device <id|label>")
    return 0


def cmd_encoders(args) -> int:
    """List the best available encoder per codec, plus the raw candidate chain."""
    si = probe_system(args.ffmpeg)
    if getattr(args, "json", False):
        print(json.dumps(system_info_to_dict(si)["best_encoders"], indent=2))
        return 0
    print(bold(f"\n{APP_NAME} {VERSION} — available video encoders\n"))
    for codec in ("h264", "hevc", "av1"):
        print(f"  {bold(codec)}")
        for enc_name, kind in _candidate_encoders(si, codec):
            present = enc_name in si.encoders
            tag = green("available") if present else dim("missing")
            chosen = ""
            try:
                if present and choose_encoder(si, codec).name == enc_name:
                    chosen = cyan("  ← selected")
            except SystemExit:
                pass
            print(f"    {enc_name:<18} {dim('(' + kind + ')'):<16} {tag}{chosen}")
        print()
    return 0


def cmd_gui(args) -> int:
    return launch_gui(args.ffmpeg)


def build_parser(rc: Optional[dict] = None) -> argparse.ArgumentParser:
    rc = rc or {}

    def d(key, fallback):
        """Default for an arg: RC file value if present, else hard fallback."""
        return rc.get(key, fallback)

    p = argparse.ArgumentParser(
        prog="turborec",
        description=f"{APP_NAME} {VERSION} — cross-platform hardware-accelerated screen & audio recorder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  turborec detect                 # show what was auto-detected\n"
            "  turborec detect --json          # machine-readable probe (scripts/CI)\n"
            "  turborec devices                # list mics + system-audio sources\n"
            "  turborec encoders               # show the HW/SW encoder chain\n"
            "  turborec gui                    # graphical interface\n"
            "  turborec record                 # best video + mic + system audio\n"
            "  turborec record -m video_mic -q high -f 30\n"
            "  turborec record -t 5m --countdown 3 --open\n"
            "  turborec record -m audio_both --audio-codec flac\n"
            "\n"
            "config:\n"
            "  Defaults can be set in ~/.config/turborec/config.json, ~/.turborec.json,\n"
            "  or $TURBOREC_CONFIG (JSON; e.g. {\"quality\": \"high\", \"fps\": 30}).\n"
            "  Any CLI flag overrides the config file.\n"
            "\n"
            "shell completion (bash):\n"
            "  register-python-argcomplete turborec  # if 'argcomplete' is installed\n"
            "  # or simply:  complete -W \"detect devices encoders gui record\" turborec\n"
        ),
    )
    p.add_argument("--ffmpeg", default=d("ffmpeg", None), help="path to ffmpeg binary")
    p.add_argument("--config", default=None,
                   help="path to an extra JSON config file (highest precedence)")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    sub = p.add_subparsers(dest="command")

    det = sub.add_parser("detect", help="probe the system and print capabilities")
    det.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    det.set_defaults(func=cmd_detect)

    dev = sub.add_parser("devices", help="list microphones and system-audio sources")
    dev.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    dev.set_defaults(func=cmd_devices)

    enc = sub.add_parser("encoders", help="list available video encoders per codec")
    enc.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    enc.set_defaults(func=cmd_encoders)

    tgt = sub.add_parser("targets", help="list capture targets (screen, monitors, windows)")
    tgt.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    tgt.set_defaults(func=cmd_targets)

    sub.add_parser("gui", help="launch the graphical interface").set_defaults(func=cmd_gui)

    r = sub.add_parser("record", help="record screen and/or audio")
    r.add_argument("-m", "--mode", choices=MODES, default=d("mode", "video_both"),
                   help="what to capture (default: video_both)")
    r.add_argument("-q", "--quality", choices=QUALITY_LEVELS, default=d("quality", "best"),
                   help="quality preset (default: best)")
    r.add_argument("-R", "--resolution", choices=RESOLUTIONS, default=d("resolution", "native"),
                   help="output resolution: native (default), 720p, 1080p, 1440p, 4k — "
                        "scales the recording (upscale to 4k for YouTube's 4K tier)")
    r.add_argument("-c", "--codec", choices=("h264", "hevc", "av1"), default=d("codec", "h264"),
                   help="video codec (default: h264)")
    r.add_argument("-f", "--fps", type=int, default=d("fps", 60),
                   help="frames per second (default: 60)")
    r.add_argument("-o", "--out", default=d("out", None), help="output directory")
    r.add_argument("-t", "--duration", type=parse_duration, default=d("duration", None),
                   metavar="TIME",
                   help="auto-stop after TIME (e.g. 90, 90s, 5m, 1h30m, HH:MM:SS)")
    r.add_argument("--countdown", type=int, default=d("countdown", 0), metavar="N",
                   help="wait N seconds before recording starts (default: 0)")
    r.add_argument("--open", action="store_true", default=bool(d("open", False)),
                   help="open the finished file with the default app")
    r.add_argument("--region", default=d("region", None),
                   help="explicit capture region WxH or WxH+X+Y (default: full screen)")
    r.add_argument("--monitor", default=d("monitor", None), metavar="NAME",
                   help="capture a specific monitor by name (see: turborec targets)")
    r.add_argument("--window", default=d("window", None), metavar="TITLE",
                   help="capture a specific window by title/id (see: turborec targets)")
    r.add_argument("--audio-rate", type=int, default=d("audio_rate", 48000),
                   help="audio sample rate (default: 48000)")
    r.add_argument("--audio-codec", choices=("flac", "aac", "opus"), default=d("audio_codec", "flac"),
                   help="audio codec (default: flac, lossless)")
    r.add_argument("--audio-channels", choices=("stereo", "mono", "left", "right"),
                   default=d("audio_channels", "stereo"),
                   help="channel handling: stereo (default), mono (average), or "
                        "left/right (clone that channel to both — fixes one-sided audio)")
    r.add_argument("--container", default=d("container", "mkv"), help="video container (default: mkv)")
    r.add_argument("--mic-device", default=d("mic_device", None),
                   help="microphone device id/name (default: auto)")
    r.add_argument("--system-device", default=d("system_device", None),
                   help="system-audio source id/name (default: auto)")
    r.add_argument("--backend", choices=("auto", "gpu", "cpu"), default=d("backend", "auto"),
                   help="encoder backend: auto (default), gpu (hardware), cpu (software)")
    r.add_argument("--gpu", action="store_true", help="shorthand for --backend gpu")
    r.add_argument("--cpu", action="store_true", help="shorthand for --backend cpu")
    r.add_argument("--software", action="store_true", default=bool(d("software", False)),
                   help="alias for --cpu (force CPU/software encoding)")
    r.add_argument("--stream", metavar="KEY", default=None,
                   help="go LIVE instead of recording to a file — pass your YouTube "
                        "(or other RTMP) stream key, OBS-style")
    r.add_argument("--stream-url", metavar="URL", default=d("stream_url", None),
                   help=f"RTMP(S) ingest URL for --stream (default: YouTube, {YOUTUBE_INGEST})")
    r.add_argument("--dry-run", action="store_true", help="print the ffmpeg command and exit")
    r.add_argument("--quiet", action="store_true", default=bool(d("quiet", False)),
                   help="suppress the detection summary line")
    r.set_defaults(func=cmd_record)
    return p


# ---------------------------------------------------------------------------
# GUI theme constants & helpers (stdlib tkinter only)
# ---------------------------------------------------------------------------
# Single source of truth for the dark "Obsidian / Telemetry" cyan theme.
_GUI_THEME = {
    "bg":       "#06090b",   # near-black window background
    "surface":  "#0b1014",   # cards / header / footer dock
    "surface2": "#121a20",   # inputs, combos, segment tracks
    "surface3": "#1a242b",   # hover / pressed surfaces
    "accent":   "#19e3d6",   # cyan primary accent
    "accent2":  "#5cf2e8",   # brighter cyan (hover/glow)
    "text":     "#e6f1f4",   # primary text
    "muted":    "#6b8893",   # secondary / labels / hints
    "faint":    "#3a4750",   # disabled text
    "danger":   "#ff2e55",   # recording red
    "danger2":  "#7a0e22",   # dim red (pulse trough)
    "warn":     "#f5b441",   # software-fallback amber
    "success":  "#19f7c8",   # saved / present green-cyan
    "border":   "#16323b",   # hairline borders
}

# Single sentinel string for the "no device" placeholder. Referenced anywhere
# a combobox may legitimately hold "no selection" (device dot logic, find_dev).
# Centralised here so the literal is never duplicated/fragile.
_GUI_NONE = "(none)"


def _gui_pick_font(tkfont, candidates, default="TkDefaultFont"):
    """Return the first available font family from candidates, else default."""
    try:
        available = {f.lower() for f in tkfont.families()}
    except Exception:  # noqa: BLE001
        return default
    for fam in candidates:
        if fam.lower() in available:
            return fam
    return default


def _gui_fmt_elapsed(seconds: int) -> str:
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _gui_fmt_size(num_bytes: int) -> str:
    n = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return f"{n:.1f} TB"


# Short, friendly labels for the segmented Mode control -> real MODES values.
_GUI_MODE_LABELS = (
    ("video_both",   "Screen + All"),
    ("video_mic",    "Screen + Mic"),
    ("video_system", "Screen + Sys"),
    ("video_only",   "Screen"),
    ("audio_both",   "Audio All"),
    ("audio_mic",    "Mic"),
    ("audio_system", "Sys"),
)


def _gui_build_preview(si, spec):
    """build_plan() for the *preview* path — never mutates the filesystem.

    build_plan()/build_command() call ensure_dir(out_dir) -> os.makedirs(), which
    would (a) create directories merely by opening the GUI / editing the Folder
    field and (b) raise OSError for an unwritable path. The live preview must be a
    pure read of the configuration, so build_plan is invoked with preview=True and
    we additionally neutralise ensure_dir (build_command, used on the non-Wayland
    path, calls it unconditionally). Returns a RecordPlan.
    """
    g = globals()
    real_ensure_dir = g.get("ensure_dir")
    g["ensure_dir"] = lambda _path: None
    try:
        return build_plan(si, spec, preview=True)
    finally:
        if real_ensure_dir is not None:
            g["ensure_dir"] = real_ensure_dir


# ---------------------------------------------------------------------------
# GUI (Tkinter) — optional; degrades gracefully if Tk is missing
# ---------------------------------------------------------------------------
def launch_gui(ffmpeg: Optional[str]) -> int:
    try:
        import tkinter as tk  # noqa: PLC0415
        from tkinter import ttk, filedialog, messagebox  # noqa: PLC0415
        from tkinter import font as tkfont  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        err("Tkinter is not available in this Python install.")
        err("  • Debian/Ubuntu:  sudo apt install python3-tk")
        err("  • Fedora:         sudo dnf install python3-tkinter")
        err("  • Arch:           sudo pacman -S tk")
        err("  • macOS/Windows:  use the python.org installer (bundles Tk)")
        err("You can still use the full CLI:  turborec record …")
        return 2

    si = probe_system(ffmpeg)
    C = _GUI_THEME

    root = tk.Tk()
    root.title(f"{APP_NAME} {VERSION}")
    root.configure(bg=C["bg"])
    root.minsize(620, 660)
    try:
        root.geometry("640x720")
    except Exception:  # noqa: BLE001
        pass

    # ---- fonts (resolved with safe fallbacks) -----------------------------
    sans_fam = _gui_pick_font(
        tkfont, ("Inter", "SF Pro Text", "Segoe UI", "Helvetica Neue", "DejaVu Sans", "Arial"))
    mono_fam = _gui_pick_font(
        tkfont, ("JetBrains Mono", "SF Mono", "Cascadia Mono", "Cascadia Code",
                 "DejaVu Sans Mono", "Consolas", "Menlo", "Courier New"))
    F = {
        "word":   (sans_fam, 13, "bold"),
        "chip":   (mono_fam, 9),
        "head":   (sans_fam, 9, "bold"),
        "label":  (sans_fam, 10),
        "value":  (sans_fam, 11),
        "btn":    (sans_fam, 12, "bold"),
        "btnsm":  (sans_fam, 9, "bold"),
        "timer":  (mono_fam, 30, "bold"),
        "sub":    (mono_fam, 9),
        "mono":   (mono_fam, 9),
        "seg":    (sans_fam, 9),
        "hint":   (sans_fam, 9),
    }

    # ---- ttk Style (clam is the only fully-restyleable built-in theme) ----
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # Dark dropdown popups (a Tk Listbox, NOT themable via ttk.Style):
    root.option_add("*TCombobox*Listbox.background", C["surface2"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["bg"])
    root.option_add("*TCombobox*Listbox.borderWidth", "0")
    root.option_add("*TCombobox*Listbox.font", F["value"])

    style.configure(
        "TR.TCombobox",
        fieldbackground=C["surface2"], background=C["surface2"],
        foreground=C["text"], arrowcolor=C["muted"],
        bordercolor=C["border"], lightcolor=C["border"], darkcolor=C["border"],
        borderwidth=1, relief="flat", padding=5,
    )
    style.map(
        "TR.TCombobox",
        fieldbackground=[("readonly", C["surface2"]), ("disabled", C["surface"]),
                         ("focus", C["surface2"])],
        foreground=[("disabled", C["faint"])],
        arrowcolor=[("active", C["accent"]), ("disabled", C["faint"])],
        bordercolor=[("focus", C["accent"])],
        selectbackground=[("readonly", C["surface2"])],
        selectforeground=[("readonly", C["text"])],
    )
    # A derived style for an orient'd widget needs its layout cloned from the
    # base ("Vertical.TScrollbar"); otherwise ttk looks up the non-existent
    # "Vertical.Vert.TScrollbar" layout and raises TclError at widget creation.
    try:
        style.layout("Vert.TScrollbar", style.layout("Vertical.TScrollbar"))
    except tk.TclError:
        pass
    style.configure("Vert.TScrollbar", background=C["surface2"],
                    troughcolor=C["surface"], bordercolor=C["surface"],
                    arrowcolor=C["muted"])

    # ---- generic tk widget helpers ---------------------------------------
    def hairline(parent, color=None):
        return tk.Frame(parent, height=1, bg=color or C["border"])

    def label(parent, text, *, fg=None, bg=None, font=None, **kw):
        return tk.Label(parent, text=text, fg=fg or C["text"],
                        bg=bg or parent["bg"], font=font or F["label"],
                        anchor="w", **kw)

    def section_header(parent, text):
        bar = tk.Frame(parent, bg=parent["bg"])
        spaced = "  ".join(text.upper())
        tk.Label(bar, text=spaced, fg=C["muted"], bg=parent["bg"],
                 font=F["head"]).pack(side="left")
        rule = tk.Frame(bar, height=1, bg=C["border"])
        rule.pack(side="left", fill="x", expand=True, padx=(10, 0), pady=(0, 0))
        return bar

    # ---- outer 1px border frame -> body -----------------------------------
    border_wrap = tk.Frame(root, bg=C["border"])
    border_wrap.pack(fill="both", expand=True, padx=1, pady=1)
    shell = tk.Frame(border_wrap, bg=C["bg"])
    shell.pack(fill="both", expand=True)

    # =======================================================================
    # HEADER BAR
    # =======================================================================
    header = tk.Frame(shell, bg=C["surface"], height=54)
    header.pack(fill="x")
    header.pack_propagate(False)

    hleft = tk.Frame(header, bg=C["surface"])
    hleft.pack(side="left", fill="y", padx=16)
    dot_canvas = tk.Canvas(hleft, width=12, height=12, bg=C["surface"],
                           highlightthickness=0, bd=0)
    dot_canvas.pack(side="left", pady=18)
    rec_dot = dot_canvas.create_oval(1, 1, 11, 11, fill=C["accent"], outline="")
    tk.Label(hleft, text=" ".join(APP_NAME.upper()), fg=C["text"],
             bg=C["surface"], font=F["word"]).pack(side="left", padx=(8, 0))

    hright = tk.Frame(header, bg=C["surface"])
    hright.pack(side="right", fill="y", padx=16)
    hw_tag = "HW" if si.has_gpu else "SW"
    sys_left = f"{si.os} · {si.display_server} · {si.gpu_vendor} "
    sys_right = f" · {si.screen or '?'}"
    sysbar = tk.Frame(hright, bg=C["surface"])
    sysbar.pack(side="right", pady=20)
    tk.Label(sysbar, text=sys_left, fg=C["muted"], bg=C["surface"],
             font=F["chip"]).pack(side="left")
    tk.Label(sysbar, text=hw_tag, fg=(C["success"] if si.has_gpu else C["warn"]),
             bg=C["surface"], font=F["chip"]).pack(side="left")
    tk.Label(sysbar, text=sys_right, fg=C["muted"], bg=C["surface"],
             font=F["chip"]).pack(side="left")

    hairline(shell).pack(fill="x")

    # =======================================================================
    # BODY (scrollable so it survives small screens)
    # =======================================================================
    body_holder = tk.Frame(shell, bg=C["bg"])
    body_holder.pack(fill="both", expand=True)

    canvas = tk.Canvas(body_holder, bg=C["bg"], highlightthickness=0, bd=0)
    vbar = ttk.Scrollbar(body_holder, orient="vertical", command=canvas.yview,
                         style="Vert.TScrollbar")
    canvas.configure(yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.pack(side="right", fill="y")

    body = tk.Frame(canvas, bg=C["bg"])
    body_win = canvas.create_window((0, 0), window=body, anchor="nw")

    def _on_body_config(_e=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
    body.bind("<Configure>", _on_body_config)

    def _on_canvas_config(e):
        canvas.itemconfigure(body_win, width=e.width)
    canvas.bind("<Configure>", _on_canvas_config)

    def _on_wheel(e):
        delta = -1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1
        canvas.yview_scroll(delta, "units")
    canvas.bind_all("<MouseWheel>", _on_wheel)
    canvas.bind_all("<Button-4>", _on_wheel)
    canvas.bind_all("<Button-5>", _on_wheel)

    inner = tk.Frame(body, bg=C["bg"])
    inner.pack(fill="both", expand=True, padx=22, pady=16)

    # ---- shared state -----------------------------------------------------
    # Every pending root.after() handle is tracked here so that on_close()/
    # _finish_recording() can cancel it before the interpreter is torn down,
    # preventing post-destroy TclError ("application has been destroyed").
    state = {"procs": None, "plan": None, "pulse_ids": None,
             "out_path": None, "size_path": None,
             "elapsed": 0,
             "recording": False, "stopping": False, "closing": False,
             "destroyed": False, "pulse": 0,
             "after_tick": None, "after_pulse": None, "after_preview": None,
             "after_refresh": None, "after_copy": None, "after_close": None,
             "after_stop": None}

    def _cancel_after(key):
        h = state.get(key)
        if h is not None:
            try:
                root.after_cancel(h)
            except Exception:  # noqa: BLE001
                pass
            state[key] = None

    def _cancel_all_after():
        for key in ("after_tick", "after_pulse", "after_preview",
                    "after_refresh", "after_copy", "after_close", "after_stop"):
            _cancel_after(key)

    mode_var = tk.StringVar(value="video_both")
    quality_var = tk.StringVar(value="best")
    res_var = tk.StringVar(value="native")
    codec_var = tk.StringVar(value="h264")
    fps_var = tk.StringVar(value="60")
    acodec_var = tk.StringVar(value="flac")
    achan_var = tk.StringVar(value="stereo")
    region_var = tk.StringVar(value="")
    mic_var = tk.StringVar()
    mon_var = tk.StringVar()
    out_var = tk.StringVar(
        value=os.path.join(os.path.expanduser("~"), "Videos"))
    backend_var = tk.StringVar(value="auto")   # auto | gpu | cpu
    source_var = tk.StringVar()                # selected capture target label
    cap_targets = {"list": [], "map": {}}      # refreshed by _refresh_sources()
    user_picked_dir = {"v": False}

    # =====================================================================
    # SECTION: CAPTURE
    # =====================================================================
    section_header(inner, "Capture").pack(fill="x", pady=(0, 8))

    # --- segmented Mode control (two rows of button-look radios) ---
    seg_buttons = {}

    def _restyle_segments(*_a):
        cur = mode_var.get()
        for value, btn in seg_buttons.items():
            if value == cur:
                btn.configure(bg=C["accent"], fg=C["bg"],
                              activebackground=C["accent"], activeforeground=C["bg"])
            else:
                btn.configure(bg=C["surface2"], fg=C["muted"],
                              activebackground=C["surface3"], activeforeground=C["text"])

    def _make_seg_row(parent, items):
        rowf = tk.Frame(parent, bg=C["bg"])
        for value, text in items:
            b = tk.Radiobutton(
                rowf, text=text, value=value, variable=mode_var,
                indicatoron=0, bd=0, highlightthickness=0, relief="flat",
                font=F["seg"], padx=10, pady=6, cursor="hand2",
                selectcolor=C["surface2"], bg=C["surface2"], fg=C["muted"],
                activebackground=C["surface3"], activeforeground=C["text"],
                takefocus=0,
            )
            b.pack(side="left", padx=(0, 4))
            seg_buttons[value] = b
        return rowf

    _make_seg_row(inner, _GUI_MODE_LABELS[:4]).pack(fill="x", pady=(0, 4))
    _make_seg_row(inner, _GUI_MODE_LABELS[4:]).pack(fill="x", pady=(0, 10))

    # --- combo grid: Quality / Codec / FPS ---
    grid = tk.Frame(inner, bg=C["bg"])
    grid.pack(fill="x")
    for col in range(6):
        grid.columnconfigure(col, weight=(1 if col % 2 else 0))

    def _combo(parent, var, values, state_="readonly"):
        cb = ttk.Combobox(parent, textvariable=var, values=list(values),
                          state=state_, style="TR.TCombobox", font=F["value"])
        return cb

    label(grid, "Quality", fg=C["muted"]).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
    quality_cb = _combo(grid, quality_var, QUALITY_LEVELS)
    quality_cb.grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=4)
    label(grid, "Codec", fg=C["muted"]).grid(row=0, column=2, sticky="w", padx=(0, 8), pady=4)
    codec_cb = _combo(grid, codec_var, ("h264", "hevc", "av1"))
    codec_cb.grid(row=0, column=3, sticky="ew", padx=(0, 14), pady=4)
    label(grid, "FPS", fg=C["muted"]).grid(row=0, column=4, sticky="w", padx=(0, 8), pady=4)
    fps_cb = _combo(grid, fps_var, ("23", "24", "30", "48", "60", "120"))
    fps_cb.grid(row=0, column=5, sticky="ew", pady=4)
    label(grid, "Output", fg=C["muted"]).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
    res_cb = _combo(grid, res_var, RESOLUTIONS)
    res_cb.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=4)
    res_hint = label(grid, "native = capture size · 4k best for YouTube",
                     fg=C["faint"], font=F["hint"])
    res_hint.grid(row=1, column=2, columnspan=4, sticky="w", pady=4)

    # encoder transparency chip
    enc_chip = label(inner, "", fg=C["muted"], font=F["chip"])
    enc_chip.pack(fill="x", pady=(6, 0))

    # --- capture source picker (OBS-style: full screen / monitor / window) ---
    src_row = tk.Frame(inner, bg=C["bg"])
    src_row.pack(fill="x", pady=(8, 0))
    label(src_row, "Source", fg=C["muted"], width=8).pack(side="left", padx=(0, 8))
    source_cb = _combo(src_row, source_var, [])
    source_cb.pack(side="left", fill="x", expand=True)
    src_refresh = tk.Button(
        src_row, text="⟳", font=(sans_fam, 11), bd=0, relief="flat",
        highlightthickness=0, cursor="hand2", bg=C["bg"], fg=C["muted"],
        activebackground=C["bg"], activeforeground=C["accent"], takefocus=0)
    src_refresh.pack(side="left", padx=(6, 0))

    def _refresh_sources(*_a):
        targets = detect_capture_targets(si)
        cap_targets["list"] = targets
        cap_targets["map"] = {t.label: t for t in targets}
        labels = [t.label for t in targets]
        source_cb.configure(values=labels)
        if source_var.get() not in cap_targets["map"]:
            source_var.set(labels[0] if labels else "")
    src_refresh.configure(command=_refresh_sources)
    _refresh_sources()

    # region row (video modes only) — advanced override of the Source above
    region_row = tk.Frame(inner, bg=C["bg"])
    region_row.pack(fill="x", pady=(6, 0))
    label(region_row, "Region", fg=C["muted"]).pack(side="left", padx=(0, 8))
    region_entry = tk.Entry(
        region_row, textvariable=region_var, width=12,
        bg=C["surface2"], fg=C["text"], insertbackground=C["accent"],
        relief="flat", bd=0, highlightthickness=1,
        highlightbackground=C["border"], highlightcolor=C["accent"],
        font=F["value"])
    region_entry.pack(side="left", ipady=4)
    region_hint = label(region_row, "", fg=C["faint"], font=F["hint"])
    region_hint.pack(side="left", padx=(10, 0))

    # =====================================================================
    # SECTION: AUDIO
    # =====================================================================
    tk.Frame(inner, bg=C["bg"], height=12).pack(fill="x")
    audio_hdr_wrap = tk.Frame(inner, bg=C["bg"])
    audio_hdr_wrap.pack(fill="x", pady=(0, 8))
    section_header(audio_hdr_wrap, "Audio").pack(side="left", fill="x", expand=True)

    def _dev_lists():
        mic_labels = [m.label for m in si.mics] or [_GUI_NONE]
        mon_labels = [m.label for m in si.monitors] or [_GUI_NONE]
        return mic_labels, mon_labels

    mic_labels, mon_labels = _dev_lists()
    mic_var.set(si.default_mic.label if si.default_mic else mic_labels[0])
    mon_var.set(si.default_monitor.label if si.default_monitor else mon_labels[0])

    # refresh button (re-probe audio)
    refresh_btn = tk.Button(
        audio_hdr_wrap, text="⟳", font=(sans_fam, 11), bd=0, relief="flat",
        highlightthickness=0, cursor="hand2",
        bg=C["bg"], fg=C["muted"], activebackground=C["bg"],
        activeforeground=C["accent"], takefocus=0)
    refresh_btn.pack(side="right")

    def _dev_status_dot(parent, on):
        cv = tk.Canvas(parent, width=12, height=12, bg=parent["bg"],
                       highlightthickness=0, bd=0)
        if on:
            cv.create_oval(2, 2, 10, 10, fill=C["accent"], outline="")
        else:
            cv.create_oval(2, 2, 10, 10, fill="", outline=C["muted"], width=1)
        return cv

    mic_row = tk.Frame(inner, bg=C["bg"])
    mic_row.pack(fill="x", pady=3)
    mic_dot_holder = tk.Frame(mic_row, bg=C["bg"], width=16)
    mic_dot_holder.pack(side="left")
    mic_label_w = label(mic_row, "Microphone", fg=C["muted"], width=12)
    mic_label_w.pack(side="left", padx=(4, 8))
    mic_cb = _combo(mic_row, mic_var, mic_labels)
    mic_cb.pack(side="left", fill="x", expand=True)

    mon_row = tk.Frame(inner, bg=C["bg"])
    mon_row.pack(fill="x", pady=3)
    mon_dot_holder = tk.Frame(mon_row, bg=C["bg"], width=16)
    mon_dot_holder.pack(side="left")
    mon_label_w = label(mon_row, "System audio", fg=C["muted"], width=12)
    mon_label_w.pack(side="left", padx=(4, 8))
    mon_cb = _combo(mon_row, mon_var, mon_labels)
    mon_cb.pack(side="left", fill="x", expand=True)

    acodec_row = tk.Frame(inner, bg=C["bg"])
    acodec_row.pack(fill="x", pady=(6, 0))
    label(acodec_row, "Audio codec", fg=C["muted"], width=12).pack(side="left", padx=(20, 8))
    acodec_cb = _combo(acodec_row, acodec_var, ("flac", "aac", "opus"))
    acodec_cb.configure(width=8)
    acodec_cb.pack(side="left")
    acodec_hint = label(acodec_row, "lossless", fg=C["faint"], font=F["hint"])
    acodec_hint.pack(side="left", padx=(10, 0))
    # channel handling — fixes one-sided audio (mono mic on one input, etc.)
    label(acodec_row, "Channels", fg=C["muted"]).pack(side="left", padx=(16, 8))
    achan_cb = _combo(acodec_row, achan_var, ("stereo", "mono", "left", "right"))
    achan_cb.configure(width=8)
    achan_cb.pack(side="left")

    def _has_dev(value):
        # A device combobox holds a real selection iff it is neither the
        # "(none)" sentinel nor empty. Centralised so the sentinel comparison
        # lives in one place (see also find_dev()).
        return value not in (_GUI_NONE, "")

    def _refresh_dev_dots():
        for child in mic_dot_holder.winfo_children():
            child.destroy()
        for child in mon_dot_holder.winfo_children():
            child.destroy()
        _dev_status_dot(mic_dot_holder, _has_dev(mic_var.get())).pack()
        _dev_status_dot(mon_dot_holder, _has_dev(mon_var.get())).pack()

    # =====================================================================
    # SECTION: OUTPUT
    # =====================================================================
    tk.Frame(inner, bg=C["bg"], height=12).pack(fill="x")
    section_header(inner, "Output").pack(fill="x", pady=(0, 8))

    out_row = tk.Frame(inner, bg=C["bg"])
    out_row.pack(fill="x")
    label(out_row, "Folder", fg=C["muted"], width=12).pack(side="left", padx=(0, 8))
    out_entry = tk.Entry(
        out_row, textvariable=out_var,
        bg=C["surface2"], fg=C["text"], insertbackground=C["accent"],
        relief="flat", bd=0, highlightthickness=1,
        highlightbackground=C["border"], highlightcolor=C["accent"],
        font=F["value"])
    out_entry.pack(side="left", fill="x", expand=True, ipady=4)

    def _hoverable(btn, base, hover, fg_base=None, fg_hover=None):
        btn.bind("<Enter>", lambda _e: btn.configure(
            bg=hover, fg=(fg_hover or btn.cget("fg"))))
        btn.bind("<Leave>", lambda _e: btn.configure(
            bg=base, fg=(fg_base or btn.cget("fg"))))

    def _browse():
        user_picked_dir["v"] = True
        d = filedialog.askdirectory(initialdir=out_var.get() or os.path.expanduser("~"))
        if d:
            out_var.set(d)

    browse_btn = tk.Button(
        out_row, text="…", command=_browse, font=F["value"], bd=0, relief="flat",
        highlightthickness=0, cursor="hand2", padx=12,
        bg=C["surface2"], fg=C["text"], activebackground=C["surface3"],
        activeforeground=C["text"], takefocus=0)
    browse_btn.pack(side="left", padx=(6, 0))
    _hoverable(browse_btn, C["surface2"], C["surface3"])

    fname_preview = label(inner, "", fg=C["muted"], font=F["mono"])
    fname_preview.pack(fill="x", pady=(6, 0))

    # --- LIVE streaming (OBS-style): paste a stream key to go live instead of recording ---
    stream_var = tk.StringVar(value="")
    stream_row = tk.Frame(inner, bg=C["bg"])
    stream_row.pack(fill="x", pady=(8, 0))
    label(stream_row, "Stream key", fg=C["muted"], width=12).pack(side="left", padx=(0, 8))
    stream_entry = tk.Entry(
        stream_row, textvariable=stream_var, show="•",
        bg=C["surface2"], fg=C["text"], insertbackground=C["accent"],
        relief="flat", bd=0, highlightthickness=1,
        highlightbackground=C["border"], highlightcolor=C["accent"], font=F["value"])
    stream_entry.pack(side="left", fill="x", expand=True, ipady=4)
    label(stream_row, "→ YouTube (blank = record)", fg=C["faint"], font=F["hint"]).pack(side="left", padx=(10, 0))

    # --- encoder backend segmented control: Auto / GPU / CPU ---
    enc_row = tk.Frame(inner, bg=C["bg"])
    enc_row.pack(fill="x", pady=(10, 0))
    label(enc_row, "Encoder", fg=C["muted"], width=8).pack(side="left", padx=(0, 8))
    backend_buttons = {}
    _BACKEND_ITEMS = (("auto", "Auto"), ("gpu", "GPU"), ("cpu", "CPU"))

    def _restyle_backend(*_a):
        cur = backend_var.get()
        for value, btn in backend_buttons.items():
            if value == cur:
                btn.configure(bg=C["accent"], fg=C["bg"],
                              activebackground=C["accent"], activeforeground=C["bg"])
            else:
                btn.configure(bg=C["surface2"], fg=C["muted"],
                              activebackground=C["surface3"], activeforeground=C["text"])

    for value, text in _BACKEND_ITEMS:
        b = tk.Radiobutton(
            enc_row, text=text, value=value, variable=backend_var,
            indicatoron=0, bd=0, highlightthickness=0, relief="flat",
            font=F["seg"], padx=14, pady=5, cursor="hand2",
            selectcolor=C["surface2"], bg=C["surface2"], fg=C["muted"],
            activebackground=C["surface3"], activeforeground=C["text"], takefocus=0)
        b.pack(side="left", padx=(0, 4))
        backend_buttons[value] = b

    # =====================================================================
    # SECTION: COMMAND PREVIEW (collapsible)
    # =====================================================================
    tk.Frame(inner, bg=C["bg"], height=12).pack(fill="x")
    prev_hdr = tk.Frame(inner, bg=C["bg"])
    prev_hdr.pack(fill="x")
    preview_open = {"v": False}
    chevron = tk.Label(prev_hdr, text="›  command preview", fg=C["muted"],
                       bg=C["bg"], font=F["head"], cursor="hand2", anchor="w")
    chevron.pack(side="left")
    copy_btn = tk.Label(prev_hdr, text="copy", fg=C["muted"], bg=C["bg"],
                        font=F["hint"], cursor="hand2")
    copy_btn.pack(side="right")

    preview_box = tk.Text(
        inner, height=5, wrap="word", bg=C["surface"], fg=C["muted"],
        relief="flat", bd=0, highlightthickness=1,
        highlightbackground=C["border"], highlightcolor=C["border"],
        font=F["mono"], padx=8, pady=6, insertbackground=C["accent"])
    preview_box.tag_configure("err", foreground=C["danger"])

    def _set_preview_text(text, is_err=False):
        preview_box.configure(state="normal")
        preview_box.delete("1.0", "end")
        preview_box.insert("1.0", text, ("err",) if is_err else ())
        preview_box.configure(state="disabled")

    def _toggle_preview(_e=None):
        preview_open["v"] = not preview_open["v"]
        if preview_open["v"]:
            chevron.configure(text="⌄  command preview")
            preview_box.pack(fill="x", pady=(6, 0))
        else:
            chevron.configure(text="›  command preview")
            preview_box.pack_forget()
    chevron.bind("<Button-1>", _toggle_preview)

    def _copy_cmd(_e=None):
        txt = preview_box.get("1.0", "end").strip()
        if txt:
            root.clipboard_clear()
            root.clipboard_append(txt)
            copy_btn.configure(text="copied", fg=C["success"])
            _cancel_after("after_copy")
            state["after_copy"] = root.after(
                1200, lambda: copy_btn.configure(text="copy", fg=C["muted"]))
    copy_btn.bind("<Button-1>", _copy_cmd)

    # =======================================================================
    # FOOTER DOCK (pinned bottom): timer + state + size  |  big action button
    # =======================================================================
    hairline(shell).pack(fill="x", side="bottom")
    footer = tk.Frame(shell, bg=C["surface"], height=92)
    footer.pack(fill="x", side="bottom")
    footer.pack_propagate(False)

    fleft = tk.Frame(footer, bg=C["surface"])
    fleft.pack(side="left", fill="y", padx=18, pady=12)
    timer_lbl = tk.Label(fleft, text="00:00:00", fg=C["accent"],
                         bg=C["surface"], font=F["timer"], anchor="w")
    timer_lbl.pack(anchor="w")
    state_line = tk.Label(fleft, text="idle", fg=C["muted"], bg=C["surface"],
                          font=F["sub"], anchor="w")
    state_line.pack(anchor="w")
    size_line = tk.Label(fleft, text="0.0 MB", fg=C["muted"], bg=C["surface"],
                         font=F["sub"], anchor="w")
    size_line.pack(anchor="w")

    # action button: cyan ghost START -> solid red STOP. tk.Button inside a
    # 1px frame border so the ghost outline is crisp.
    fright = tk.Frame(footer, bg=C["surface"])
    fright.pack(side="right", fill="y", padx=18, pady=18)
    btn_border = tk.Frame(fright, bg=C["accent"])
    btn_border.pack(fill="both", expand=True)
    action_btn = tk.Button(
        btn_border, text="●  START", font=F["btn"], bd=0, relief="flat",
        highlightthickness=0, cursor="hand2", width=18,
        bg=C["bg"], fg=C["accent"], activebackground="#06222a",
        activeforeground=C["accent2"], takefocus=0)
    action_btn.pack(fill="both", expand=True, padx=1, pady=1)

    # ---- mode-aware logic -------------------------------------------------
    def _wants(mode):
        wm = mode in ("video_both", "video_mic", "audio_mic", "audio_both")
        ws = mode in ("video_both", "video_system", "audio_system", "audio_both")
        return wm, ws

    def _set_row_enabled(widgets, enabled):
        for w in widgets:
            try:
                if isinstance(w, ttk.Combobox):
                    w.configure(state=("readonly" if enabled else "disabled"))
                else:
                    w.configure(fg=(C["muted"] if enabled else C["faint"]))
            except tk.TclError:
                pass

    def _refresh_dependent(*_a):
        mode = mode_var.get()
        is_video = mode.startswith("video")
        wm, ws = _wants(mode)

        # video-only rows
        vid_state = "readonly" if is_video else "disabled"
        for cb in (quality_cb, codec_cb, fps_cb, res_cb):
            cb.configure(state=vid_state)
        region_entry.configure(state=("normal" if is_video else "disabled"))
        region_hint.configure(
            text=(f"blank = full screen {si.screen or '?'}" if is_video else "n/a for audio modes"),
            fg=C["faint"])

        # audio rows
        _set_row_enabled([mic_label_w, mic_cb], wm)
        _set_row_enabled([mon_label_w, mon_cb], ws)

        # encoder transparency chip
        if is_video:
            if si.os == "linux" and si.display_server == "wayland":
                try:
                    spec = _current_spec()
                except Exception:  # noqa: BLE001
                    spec = RecordSpec(mode=mode_var.get(), codec=codec_var.get(),
                                      backend=backend_var.get())
                name, _p, kind, _d = wf_codec(si, spec)
                fg = C["warn"] if kind == "software" else C["accent"]
                enc_chip.configure(text=f"{name}  ·  {kind}  ·  wf-recorder (Wayland)", fg=fg)
            else:
                try:
                    ec = choose_encoder(si, codec_var.get(), False, backend_var.get())
                    fg = C["warn"] if ec.kind == "software" else C["accent"]
                    enc_chip.configure(text=f"{ec.name}  ·  {ec.kind}  ·  {ec.note}", fg=fg)
                except SystemExit:
                    enc_chip.configure(text="no usable encoder for this codec", fg=C["warn"])
        else:
            enc_chip.configure(text="audio-only — no video encoder", fg=C["faint"])

        # audio codec hint
        acodec_hint.configure(text={"flac": "lossless", "aac": "320k",
                                    "opus": "256k"}.get(acodec_var.get(), ""))

        # default output dir follows mode unless user picked one
        if not user_picked_dir["v"]:
            sub = "Videos" if is_video else "Audio"
            out_var.set(os.path.join(os.path.expanduser("~"), sub))

        _refresh_dev_dots()
        _restyle_segments()
        _restyle_backend()

    # ---- build a spec from the current widgets ----------------------------
    def find_dev(devs, lab, fallback_monitor=False):
        d = next((x for x in devs if x.label == lab), None)
        if d is None and _has_dev(lab):
            d = AudioDevice(id=lab, label=lab, is_monitor=fallback_monitor)
        return d

    def _current_spec():
        try:
            fps = int(fps_var.get())
        except ValueError:
            fps = 60
        # Capture target: explicit Region overrides the Source picker; otherwise a
        # monitor/window target; "screen" => full. _apply_target_to_spec fills the
        # right fields for X11 (geometry/win_title) or Wayland (wl_output/wl_geometry).
        region_override = region_var.get().strip() or None
        if region_override:
            target = CaptureTarget(kind="region", label="region", geometry=region_override)
        else:
            t = cap_targets["map"].get(source_var.get())
            target = t if (t and t.kind != "screen") else None
        key = stream_var.get().strip() or None
        spec = RecordSpec(
            mode=mode_var.get(),
            quality=quality_var.get(),
            resolution=res_var.get(),
            codec=codec_var.get(),
            fps=fps,
            out_dir=out_var.get(),
            audio_codec=acodec_var.get(),
            audio_channels=achan_var.get(),
            mic=find_dev(si.mics, mic_var.get()),
            monitor=find_dev(si.monitors, mon_var.get(), fallback_monitor=True),
            backend=backend_var.get(),
            stream_url=(_stream_target("", key) if key else None),
            stream_secret=key,
        )
        _apply_target_to_spec(si, target, spec)
        return spec

    # ---- live command preview (debounced) ---------------------------------
    def _do_preview():
        state["after_preview"] = None
        if state["destroyed"]:
            return
        spec = _current_spec()
        try:
            # Use the preview-safe builder: it neutralises ensure_dir so that
            # merely opening the GUI or typing in the Folder field never creates
            # directories on disk, and so an unwritable/invalid path cannot raise
            # OSError out of this Tk callback. We still defensively catch OSError
            # (and any other Exception) in case build_command grows other I/O.
            plan = _gui_build_preview(si, spec)
        except SystemExit as e:
            msg = str(e) or "invalid configuration"
            fname_preview.configure(text="—", fg=C["faint"])
            _set_preview_text(f"cannot build command: {msg}", is_err=True)
            if not (state["recording"] or state["stopping"]):
                state_line.configure(text=msg, fg=C["danger"])
                action_btn.configure(state="disabled")
            return
        except OSError as e:
            fname_preview.configure(text="—", fg=C["faint"])
            _set_preview_text(f"cannot build command: {e}", is_err=True)
            if not (state["recording"] or state["stopping"]):
                state_line.configure(text="output path error", fg=C["danger"])
                action_btn.configure(state="disabled")
            return
        except Exception as e:  # noqa: BLE001
            fname_preview.configure(text="—", fg=C["faint"])
            _set_preview_text(f"cannot build command: {e}", is_err=True)
            if not (state["recording"] or state["stopping"]):
                state_line.configure(text="configuration error", fg=C["danger"])
                action_btn.configure(state="disabled")
            return
        if not (state["recording"] or state["stopping"]):
            state_line.configure(text="idle", fg=C["muted"])
            action_btn.configure(state="normal")
        if plan.is_stream:
            fname_preview.configure(text="↳ ● LIVE → " + _mask_secret(plan.out_path, plan.secret),
                                    fg=C["success"])
        else:
            fname_preview.configure(text="↳ " + os.path.basename(plan.out_path), fg=C["muted"])
        lines = []
        for label, argv, _m in plan.procs:
            lines.append(f"# {label}")
            lines.append(_redact_cmd(argv, plan.secret))
        if plan.finalize:
            lines.append("# mux")
            lines.append(_redact_cmd(plan.finalize, plan.secret))
        _set_preview_text("\n".join(lines))

    def schedule_preview(*_a):
        if state["destroyed"] or state["closing"]:
            return
        _cancel_after("after_preview")
        state["after_preview"] = root.after(250, _do_preview)

    # ---- timer / pulse animations -----------------------------------------
    def _tick():
        state["after_tick"] = None
        if not state["recording"] or state["destroyed"]:
            return
        state["elapsed"] += 1
        timer_lbl.configure(text=_gui_fmt_elapsed(state["elapsed"]))
        # poll the live output size (the temp video file during a composite mux)
        try:
            p = state.get("size_path")
            if p and os.path.exists(p):
                size_line.configure(text=_gui_fmt_size(os.path.getsize(p)))
        except OSError:
            pass
        # poll for the capture process dying on its own → tear everything down
        # (stop the other process(es), unload the PipeWire mix, mux/cleanup)
        procs = state.get("procs") or []
        primary = procs[0][0] if procs else None
        if primary is not None and primary.poll() is not None and not state["stopping"]:
            do_stop(crashed=True, code=primary.returncode or 0)
            return
        state["after_tick"] = root.after(1000, _tick)

    def _pulse():
        state["after_pulse"] = None
        # Guard against firing after the interpreter/widgets are gone.
        if state["destroyed"]:
            return
        if not (state["recording"] or state["stopping"]):
            try:
                dot_canvas.itemconfigure(rec_dot, fill=C["accent"])
            except tk.TclError:
                pass
            return
        state["pulse"] ^= 1
        col = C["danger"] if state["pulse"] else C["danger2"]
        try:
            dot_canvas.itemconfigure(rec_dot, fill=col)
        except tk.TclError:
            return
        state["after_pulse"] = root.after(450, _pulse)

    # ---- start / stop -----------------------------------------------------
    def _set_recording_ui(on):
        if on:
            action_btn.configure(text="■  STOP", bg=C["danger"], fg=C["bg"],
                                  activebackground=C["danger"],
                                  activeforeground=C["bg"], state="normal")
            btn_border.configure(bg=C["danger"])
        else:
            action_btn.configure(text="●  START", bg=C["bg"], fg=C["accent"],
                                  activebackground="#06222a",
                                  activeforeground=C["accent2"], state="normal")
            btn_border.configure(bg=C["accent"])
        # lock the encoder + source controls while recording is in progress
        for b in backend_buttons.values():
            try:
                b.configure(state=("disabled" if on else "normal"))
            except tk.TclError:
                pass
        try:
            source_cb.configure(state=("disabled" if on else "readonly"))
            src_refresh.configure(state=("disabled" if on else "normal"))
        except tk.TclError:
            pass

    def do_start():
        spec = _current_spec()
        # The real start path is the ONLY place allowed to create directories,
        # so we use build_plan() directly (which calls ensure_dir()).
        try:
            plan = build_plan(si, spec)
        except SystemExit as e:
            messagebox.showerror(APP_NAME, f"Cannot start: {e}")
            return
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Cannot create output folder: {e}")
            return
        # PipeWire mix setup for synced mic+system (may switch to a fallback plan)
        plan, pulse_ids = _activate_plan(plan)
        procs = []
        try:
            for _label, argv, method in plan.procs:
                stdin = subprocess.PIPE if method == "q" else subprocess.DEVNULL
                # Mask the stream key out of a live stream child's stderr.
                stderr = subprocess.PIPE if (plan.is_stream and plan.secret) else None
                proc = subprocess.Popen(argv, stdin=stdin, stderr=stderr)
                if stderr is not None:
                    threading.Thread(target=_pump_masked_stderr,
                                     args=(proc.stderr, plan.secret), daemon=True).start()
                procs.append((proc, method))
        except OSError as e:
            for p, _m in procs:
                try:
                    p.kill()
                except OSError:
                    pass
            _pulse_mix_unload(pulse_ids)
            messagebox.showerror(APP_NAME, f"Failed to launch recorder: {e}")
            return
        state.update(procs=procs, plan=plan, pulse_ids=pulse_ids, out_path=plan.out_path,
                     size_path=(plan.cleanup[0] if plan.finalize else plan.out_path),
                     elapsed=0, recording=True, stopping=False, pulse=0)
        timer_lbl.configure(text="00:00:00")
        size_line.configure(text="0.0 MB")
        state_line.configure(text="● REC", fg=C["danger"])
        _set_recording_ui(True)
        state["after_tick"] = root.after(1000, _tick)
        _pulse()

    def _finish_recording(crashed=False, code=0):
        # called on the Tk thread once the recorder process(es) have exited
        _cancel_after("after_tick")
        _cancel_after("after_pulse")
        _cancel_after("after_stop")
        state["recording"] = False
        state["stopping"] = False
        if state["destroyed"]:
            return
        try:
            dot_canvas.itemconfigure(rec_dot, fill=C["accent"])
        except tk.TclError:
            pass
        _set_recording_ui(False)
        out_path = state.get("out_path")
        plan = state.get("plan")
        streaming = bool(plan and getattr(plan, "is_stream", False))
        saved = bool(out_path and os.path.exists(out_path) and os.path.getsize(out_path) > 0)
        if streaming:
            # For a live stream out_path is the secret-bearing RTMP URL; never
            # render it (basename would be the raw stream key). SIGINT-driven
            # exits are the normal way to stop a stream, so they aren't "crashes".
            state_line.configure(text=("Stream ended" if not crashed else f"Stream ended (code {code})"),
                                 fg=(C["success"] if not crashed else C["warn"]))
        elif crashed and not saved:
            state_line.configure(text=f"recorder exited (code {code})", fg=C["warn"])
        else:
            base = os.path.basename(out_path) if out_path else ""
            prefix = "Saved ✓" if not crashed else f"Saved (recorder stopped, code {code})"
            state_line.configure(text=f"{prefix}  {base}",
                                 fg=(C["success"] if not crashed else C["warn"]))
            try:
                if saved:
                    size_line.configure(text=_gui_fmt_size(os.path.getsize(out_path)))
            except OSError:
                pass
        state["procs"] = None
        state["plan"] = None
        state["pulse_ids"] = None
        # if a close was deferred until finalize completed, finish it now
        if state["closing"]:
            _destroy_now()

    def do_stop(crashed=False, code=0):
        procs = state.get("procs")
        if not procs:
            return
        # Guard against double-stop: pressing STOP/Escape repeatedly during the
        # finalize window must not spawn multiple stop threads / pollers.
        if state["stopping"]:
            return
        state["stopping"] = True
        plan = state.get("plan")
        pulse_ids = state.get("pulse_ids") or []
        state_line.configure(
            text=("recovering…" if crashed
                  else ("finalizing + muxing…" if (plan and plan.finalize) else "finalizing…")),
            fg=C["warn"])
        action_btn.configure(state="disabled")

        # Stop every capture process (signal all FIRST — see _stop_all: streaming
        # FIFOs deadlock otherwise), unload the PipeWire mix, then mux + clean up,
        # on a worker thread so the UI keeps animating; poll completion via after().
        def _worker():
            _stop_all(procs)
            _pulse_mix_unload(pulse_ids)
            if plan and plan.finalize:
                ok = all(os.path.exists(t) and os.path.getsize(t) > 0 for t in plan.cleanup)
                if ok:
                    try:
                        subprocess.run(plan.finalize, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
                    except OSError:
                        pass
            if plan:
                _plan_cleanup(plan)

        import threading  # noqa: PLC0415
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        def _await_stop():
            state["after_stop"] = None
            if state["destroyed"]:
                return
            if t.is_alive():
                state["after_stop"] = root.after(120, _await_stop)
                return
            _finish_recording(crashed=crashed, code=code)
        state["after_stop"] = root.after(120, _await_stop)

    def toggle_record(_e=None):
        if state["recording"] or state["stopping"]:
            do_stop()  # do_stop() now self-guards on state['stopping']
        else:
            do_start()

    action_btn.configure(command=toggle_record)

    def _action_hover(_e=None):
        if not state["recording"] and not state["stopping"] and action_btn["state"] != "disabled":
            action_btn.configure(bg="#06222a")
    def _action_leave(_e=None):
        if not state["recording"] and not state["stopping"]:
            action_btn.configure(bg=C["bg"])
    action_btn.bind("<Enter>", _action_hover)
    action_btn.bind("<Leave>", _action_leave)

    # ---- audio re-probe ---------------------------------------------------
    def do_refresh(_e=None):
        if state["recording"] or state["stopping"]:
            return
        refresh_btn.configure(fg=C["accent"])
        try:
            mics, monitors, dmic, dmon = detect_audio(si.os, si.ffmpeg)
            si.mics, si.monitors = mics, monitors
            si.default_mic, si.default_monitor = dmic, dmon
        except Exception:  # noqa: BLE001
            pass
        new_mic, new_mon = _dev_lists()
        mic_cb.configure(values=new_mic)
        mon_cb.configure(values=new_mon)
        mic_var.set(si.default_mic.label if si.default_mic else new_mic[0])
        mon_var.set(si.default_monitor.label if si.default_monitor else new_mon[0])
        _refresh_dependent()
        schedule_preview()
        _cancel_after("after_refresh")
        state["after_refresh"] = root.after(
            600, lambda: refresh_btn.configure(fg=C["muted"]))
    refresh_btn.configure(command=do_refresh)
    _hoverable(refresh_btn, C["bg"], C["bg"], C["muted"], C["accent"])

    # ---- close handling ---------------------------------------------------
    def _destroy_now():
        # central teardown: cancel every pending after() so none of them can
        # fire against a destroyed interpreter (-> TclError), then destroy.
        if state["destroyed"]:
            return
        state["destroyed"] = True
        _cancel_all_after()
        try:
            root.destroy()
        except tk.TclError:
            pass

    def _wait_for_finalize():
        # poll until the in-flight stop worker has finished; _finish_recording
        # (called by _await_stop) will invoke _destroy_now() because closing is
        # set. This is a safety net in case the proc is gone but state lingers.
        state["after_close"] = None
        if state["destroyed"]:
            return
        if state.get("procs") is None and not state["stopping"]:
            _destroy_now()
            return
        state["after_close"] = root.after(120, _wait_for_finalize)

    def on_close():
        if state["destroyed"] or state["closing"]:
            return
        procs = state.get("procs")
        # A stop may already be finalizing (stopping=True, possibly recording
        # cleared). In every "work in flight" case we must NOT destroy the UI
        # out from under the worker thread / pending pollers — defer destroy.
        if procs is not None and (state["recording"] or state["stopping"]):
            if state["stopping"]:
                # finalize already underway (e.g. user hit STOP then closed):
                # just mark closing and let _finish_recording tear down.
                state["closing"] = True
                state_line.configure(text="finalizing… closing", fg=C["warn"])
                _wait_for_finalize()
                return
            if not messagebox.askyesno(
                    APP_NAME, "Recording in progress — stop and save before exit?"):
                return
            # offload the blocking graceful stop to a daemon thread (do NOT run
            # it on the Tk main thread — that freezes the UI for up to ~15s).
            state["closing"] = True
            state_line.configure(text="finalizing… closing", fg=C["warn"])
            action_btn.configure(state="disabled")
            do_stop()          # spawns the worker thread + _await_stop poller
            _wait_for_finalize()
            return
        # nothing in flight — safe to tear down immediately.
        _destroy_now()
    root.protocol("WM_DELETE_WINDOW", on_close)

    # ---- keyboard shortcuts ----------------------------------------------
    def _on_space(_e=None):
        # don't steal the spacebar while typing in an entry/text field
        if root.focus_get() in (region_entry, out_entry, preview_box, stream_entry):
            return None
        toggle_record()
        return "break"

    def _on_escape(_e=None):
        # Escape must honour the same stopping-guard as toggle_record so it
        # cannot trigger a second do_stop during the finalize window.
        if state["recording"] and not state["stopping"]:
            do_stop()
    root.bind("<space>", _on_space)
    root.bind("<Control-r>", toggle_record)
    root.bind("<Control-o>", lambda e: _browse())
    root.bind("<Escape>", _on_escape)

    # ---- wire traces (live preview + dependent state) ---------------------
    for v in (mode_var, quality_var, res_var, codec_var, fps_var, acodec_var, achan_var,
              region_var, mic_var, mon_var, out_var, backend_var, source_var, stream_var):
        v.trace_add("write", schedule_preview)
    for v in (mode_var, codec_var, acodec_var, backend_var):
        v.trace_add("write", _refresh_dependent)
    mode_var.trace_add("write", _restyle_segments)
    backend_var.trace_add("write", _restyle_backend)
    out_var.trace_add("write", lambda *_: user_picked_dir.__setitem__("v", True)
                      if root.focus_get() is out_entry else None)

    # ---- initial paint ----------------------------------------------------
    _restyle_backend()
    _restyle_segments()
    _refresh_dependent()
    _refresh_dev_dots()
    _do_preview()  # safe: uses _gui_build_preview, no filesystem mutation

    # window icon (procedural; ignored by some WMs)
    try:
        icon = tk.PhotoImage(width=32, height=32)
        icon.put(C["accent"], to=(8, 8, 24, 24))
        root.iconphoto(True, icon)
        state["_icon"] = icon  # keep a reference
    except Exception:  # noqa: BLE001
        pass

    root.mainloop()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    # Self-contained builds (Windows .exe) ship ffmpeg alongside the app.
    _use_bundled_binaries()
    # First pass: discover --config without triggering subcommand validation,
    # so RC-file values can become argparse defaults on the real parser.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=None)
    pre_args, _ = pre.parse_known_args(argv)
    rc = load_config(pre_args.config)

    parser = build_parser(rc)
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        # no subcommand: launch GUI if possible, else show detection report
        if sys.stdout.isatty() and not os.environ.get("DISPLAY") and detect_os() == "linux":
            return cmd_detect(args)
        return cmd_gui(args)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(file=sys.stderr)
        sys.exit(130)
