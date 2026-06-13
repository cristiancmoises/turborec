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
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

APP_NAME = "Turbo Recorder"
VERSION = "2.0.0"

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


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class AudioDevice:
    id: str          # backend identifier passed to ffmpeg
    label: str       # human readable
    is_monitor: bool = False  # True for system-audio / loopback / monitor


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


# ---------------------------------------------------------------------------
# FFmpeg discovery
# ---------------------------------------------------------------------------
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
    sw = {"h264": "libx264", "hevc": "libx265", "av1": "libaom-av1"}.get(c, "libx264")
    table.append((sw, "software"))
    return table


def choose_encoder(si: SystemInfo, codec: str = "h264", force_software: bool = False) -> EncoderChoice:
    codec = codec.lower()
    if force_software:
        sw = {"h264": "libx264", "hevc": "libx265", "av1": "libaom-av1"}.get(codec, "libx264")
        if sw not in si.encoders:
            die(f"Software encoder {sw} not available in this FFmpeg build.")
        return EncoderChoice(sw, "software", codec, "forced software encoding")
    for enc, kind in _candidate_encoders(si, codec):
        if enc in si.encoders:
            note = "hardware accelerated" if kind != "software" else "software (no HW encoder available)"
            return EncoderChoice(enc, kind, codec, note)
    die(f"No usable encoder for codec {codec} in this FFmpeg build.")


# ---------------------------------------------------------------------------
# Quality presets -> encoder-specific arguments
# ---------------------------------------------------------------------------
QUALITY_LEVELS = ("best", "high", "balanced", "compact")


def _quality_index(q: str) -> int:
    return {"best": 0, "high": 1, "balanced": 2, "compact": 3}.get(q, 0)


def encoder_args(enc: EncoderChoice, quality: str) -> list[str]:
    """State-of-the-art, quality-first parameters for the chosen encoder."""
    qi = _quality_index(quality)
    a: list[str] = ["-c:v", enc.name]
    if enc.kind == "nvenc":
        # p7 = slowest/highest quality preset; constant-quality VBR
        cq = [16, 19, 23, 28][qi]
        a += ["-preset", "p7", "-tune", "hq", "-rc", "vbr",
              "-cq", str(cq), "-b:v", "0", "-spatial-aq", "1", "-temporal-aq", "1",
              "-rc-lookahead", "32", "-bf", "3"]
        if enc.codec in ("h264", "hevc"):
            a += ["-profile:v", "high" if enc.codec == "h264" else "main"]
    elif enc.kind == "qsv":
        gq = [18, 22, 26, 30][qi]
        a += ["-preset", "veryslow", "-global_quality", str(gq), "-look_ahead", "1"]
    elif enc.kind == "vaapi":
        qp = [18, 22, 26, 30][qi]
        a += ["-qp", str(qp), "-compression_level", "1"]
        if enc.codec == "h264":
            a += ["-profile:v", "high"]
    elif enc.kind == "amf":
        qp = [18, 22, 26, 30][qi]
        a += ["-quality", "quality", "-rc", "cqp", "-qp_i", str(qp), "-qp_p", str(qp)]
    elif enc.kind == "videotoolbox":
        # videotoolbox quality is 0..100 (higher = better)
        vq = [80, 65, 50, 38][qi]
        a += ["-q:v", str(vq), "-realtime", "0"]
        if enc.codec == "hevc":
            a += ["-tag:v", "hvc1"]
    else:  # software libx264 / libx265 / libaom-av1
        crf = [16, 20, 24, 28][qi]
        if enc.name == "libaom-av1":
            a += ["-crf", str(crf), "-b:v", "0", "-cpu-used", "4", "-row-mt", "1"]
        else:
            a += ["-preset", "slow", "-crf", str(crf)]
            if enc.name == "libx264":
                a += ["-profile:v", "high", "-tune", "film"]
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
def screen_input_args(si: SystemInfo, fps: int, region: Optional[str], enc: EncoderChoice) -> tuple[list[str], list[str]]:
    """Return (pre_input_args, input_args). pre_input may set vaapi device."""
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
        size = region or si.screen
        inp += ["-f", "x11grab", "-framerate", str(fps), "-thread_queue_size", "1024"]
        if size:
            inp += ["-video_size", size]
        display = os.environ.get("DISPLAY", ":0.0")
        inp += ["-i", f"{display}+0,0"]
    elif si.os == "macos":
        # "Capture screen" device index is best-effort 1; allow override via region "screenIdx"
        screen_idx = region or "1"
        inp += ["-f", "avfoundation", "-framerate", str(fps),
                "-capture_cursor", "1", "-i", f"{screen_idx}:none"]
    elif si.os == "windows":
        inp += ["-f", "gdigrab", "-framerate", str(fps), "-thread_queue_size", "1024", "-i", "desktop"]
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
    region: Optional[str] = None
    out_dir: str = ""
    audio_rate: int = 48000
    audio_codec: str = "flac"   # flac (lossless) | aac | opus
    mic: Optional[AudioDevice] = None
    monitor: Optional[AudioDevice] = None
    force_software: bool = False
    container: str = "mkv"


def _audio_encode_args(spec: RecordSpec) -> list[str]:
    if spec.audio_codec == "flac":
        return ["-c:a", "flac", "-ar", str(spec.audio_rate), "-ac", "2"]
    if spec.audio_codec == "opus":
        return ["-c:a", "libopus", "-b:a", "256k", "-ar", "48000", "-ac", "2"]
    return ["-c:a", "aac", "-b:a", "320k", "-ar", str(spec.audio_rate), "-ac", "2"]


def build_command(si: SystemInfo, spec: RecordSpec) -> tuple[list[str], str]:
    is_video = spec.mode.startswith("video")
    wants_mic = spec.mode in ("video_both", "video_mic", "audio_mic", "audio_both")
    wants_sys = spec.mode in ("video_both", "video_system", "audio_system", "audio_both")

    if wants_mic and not spec.mic:
        die("Microphone requested but no microphone device detected/selected.")
    if wants_sys and not spec.monitor:
        die("System audio requested but no monitor/loopback source detected/selected.")

    out_dir = spec.out_dir or (os.path.join(os.path.expanduser("~"), "Videos" if is_video else "Audio"))
    ensure_dir(out_dir)

    cmd: list[str] = [si.ffmpeg, "-y", "-hide_banner", "-loglevel", "info", "-stats"]

    enc = None
    audio_inputs: list[AudioDevice] = []

    if is_video:
        enc = choose_encoder(si, spec.codec, spec.force_software)
        pre, vin = screen_input_args(si, spec.fps, spec.region, enc)
        cmd += pre + vin

    # On macOS the screen+audio can come from one avfoundation device, but we
    # keep audio as separate inputs for portability and per-source control.
    if wants_sys:
        audio_inputs.append(spec.monitor)  # type: ignore[arg-type]
    if wants_mic:
        audio_inputs.append(spec.mic)      # type: ignore[arg-type]
    for dev in audio_inputs:
        cmd += audio_input_args(si, dev)

    # ---- filtergraph & mapping ----
    video_index = 0 if is_video else None
    audio_start = 1 if is_video else 0

    filtergraph_parts: list[str] = []
    maps: list[str] = []

    if is_video:
        vf = video_filter_for(enc)  # type: ignore[arg-type]
        if vf:
            filtergraph_parts.append(f"[{video_index}:v]{vf}[v]")
            maps += ["-map", "[v]"]
        else:
            maps += ["-map", f"{video_index}:v"]

    if audio_inputs:
        labels = []
        for i, _dev in enumerate(audio_inputs):
            ai = audio_start + i
            lbl = f"a{i}"
            filtergraph_parts.append(
                f"[{ai}:a]aresample={spec.audio_rate}:resampler=soxr,aformat=channel_layouts=stereo[{lbl}]"
            )
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

    # ---- encoders ----
    if is_video:
        cmd += encoder_args(enc, spec.quality)  # type: ignore[arg-type]
        # color metadata for fidelity
        cmd += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if audio_inputs:
        cmd += _audio_encode_args(spec)

    container = spec.container if is_video else ("flac" if spec.audio_codec == "flac" else ("opus" if spec.audio_codec == "opus" else "m4a"))
    name = f"{spec.mode}_{timestamp()}.{container}"
    out_path = os.path.join(out_dir, name)
    cmd.append(out_path)
    return cmd, out_path


# ---------------------------------------------------------------------------
# Recording runner (graceful stop)
# ---------------------------------------------------------------------------
def record(cmd: list[str], out_path: str, dry_run: bool = False) -> int:
    info(f"Output → {bold(out_path)}")
    info("FFmpeg command:")
    print(dim(" ".join(_shquote(c) for c in cmd)), file=sys.stderr)
    if dry_run:
        return 0
    info(f"Recording… press {bold('q')} or {bold('Ctrl-C')} to stop and finalize.")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        proc.wait()
    except KeyboardInterrupt:
        _graceful_stop(proc)
    return proc.returncode or 0


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


def _shquote(s: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:+=@%-]+", s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


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


def cmd_record(args) -> int:
    si = probe_system(args.ffmpeg)
    if not args.quiet:
        info(f"{si.os}/{si.display_server} · CPU {si.cpu_vendor} · GPU {si.gpu_vendor}"
             f"{' (HW)' if si.has_gpu else ' (SW)'} · screen {si.screen or '?'}")
    mic, mon = _resolve_audio_devices(si, args)
    spec = RecordSpec(
        mode=args.mode,
        quality=args.quality,
        codec=args.codec,
        fps=args.fps,
        region=args.region,
        out_dir=args.out or "",
        audio_rate=args.audio_rate,
        audio_codec=args.audio_codec,
        mic=mic,
        monitor=mon,
        force_software=args.software,
        container=args.container,
    )
    cmd, out_path = build_command(si, spec)
    return record(cmd, out_path, dry_run=args.dry_run)


def cmd_detect(args) -> int:
    si = probe_system(args.ffmpeg)
    print_report(si)
    return 0


def cmd_gui(args) -> int:
    return launch_gui(args.ffmpeg)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="turborec",
        description=f"{APP_NAME} {VERSION} — cross-platform hardware-accelerated screen & audio recorder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  turborec detect                 # show what was auto-detected\n"
            "  turborec gui                    # graphical interface\n"
            "  turborec record                 # best video + mic + system audio\n"
            "  turborec record -m video_mic -q high -f 30\n"
            "  turborec record -m audio_both --audio-codec flac\n"
        ),
    )
    p.add_argument("--ffmpeg", help="path to ffmpeg binary", default=None)
    sub = p.add_subparsers(dest="command")

    sub.add_parser("detect", help="probe the system and print capabilities").set_defaults(func=cmd_detect)
    sub.add_parser("gui", help="launch the graphical interface").set_defaults(func=cmd_gui)

    r = sub.add_parser("record", help="record screen and/or audio")
    r.add_argument("-m", "--mode", choices=MODES, default="video_both",
                   help="what to capture (default: video_both)")
    r.add_argument("-q", "--quality", choices=QUALITY_LEVELS, default="best",
                   help="quality preset (default: best)")
    r.add_argument("-c", "--codec", choices=("h264", "hevc", "av1"), default="h264",
                   help="video codec (default: h264)")
    r.add_argument("-f", "--fps", type=int, default=60, help="frames per second (default: 60)")
    r.add_argument("-o", "--out", help="output directory")
    r.add_argument("--region", help="capture size WxH (default: full screen); on macOS the screen device index")
    r.add_argument("--audio-rate", type=int, default=48000, help="audio sample rate (default: 48000)")
    r.add_argument("--audio-codec", choices=("flac", "aac", "opus"), default="flac",
                   help="audio codec (default: flac, lossless)")
    r.add_argument("--container", default="mkv", help="video container (default: mkv)")
    r.add_argument("--mic-device", help="microphone device id/name (default: auto)")
    r.add_argument("--system-device", help="system-audio source id/name (default: auto)")
    r.add_argument("--software", action="store_true", help="force CPU/software encoding")
    r.add_argument("--dry-run", action="store_true", help="print the ffmpeg command and exit")
    r.add_argument("--quiet", action="store_true", help="suppress the detection summary line")
    r.set_defaults(func=cmd_record)
    return p


# ---------------------------------------------------------------------------
# GUI (Tkinter) — optional; degrades gracefully if Tk is missing
# ---------------------------------------------------------------------------
def launch_gui(ffmpeg: Optional[str]) -> int:
    try:
        import tkinter as tk  # noqa: PLC0415
        from tkinter import ttk, filedialog, messagebox  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        err("Tkinter is not available in this Python install.")
        err("  • Debian/Ubuntu:  sudo apt install python3-tk")
        err("  • Fedora:         sudo dnf install python3-tkinter")
        err("  • Arch:           sudo pacman -S tk")
        err("  • macOS/Windows:  use the python.org installer (bundles Tk)")
        err("You can still use the full CLI:  turborec record …")
        return 2

    si = probe_system(ffmpeg)

    root = tk.Tk()
    root.title(f"{APP_NAME} {VERSION}")
    root.minsize(560, 520)

    state = {"proc": None}

    pad = {"padx": 8, "pady": 4}
    frm = ttk.Frame(root, padding=12)
    frm.grid(sticky="nsew")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    frm.columnconfigure(1, weight=1)

    row = 0
    summary = (f"{si.os} · {si.display_server} · CPU {si.cpu_vendor} · "
               f"GPU {si.gpu_vendor} {'(HW)' if si.has_gpu else '(software)'} · "
               f"screen {si.screen or '?'}")
    ttk.Label(frm, text=f"{APP_NAME} {VERSION}", font=("", 14, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", **pad)
    row += 1
    ttk.Label(frm, text=summary, foreground="#555").grid(row=row, column=0, columnspan=2, sticky="w", **pad)
    row += 1
    ttk.Separator(frm).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
    row += 1

    def add_combo(label, values, default):
        nonlocal row
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", **pad)
        var = tk.StringVar(value=default)
        cb = ttk.Combobox(frm, textvariable=var, values=values, state="readonly")
        cb.grid(row=row, column=1, sticky="ew", **pad)
        row += 1
        return var

    mode_var = add_combo("Mode", list(MODES), "video_both")
    quality_var = add_combo("Quality", list(QUALITY_LEVELS), "best")
    codec_var = add_combo("Video codec", ["h264", "hevc", "av1"], "h264")
    fps_var = add_combo("FPS", ["24", "30", "48", "60", "120"], "60")
    acodec_var = add_combo("Audio codec", ["flac", "aac", "opus"], "flac")

    mic_labels = [m.label for m in si.mics] or ["(none)"]
    mon_labels = [m.label for m in si.monitors] or ["(none)"]
    mic_var = add_combo("Microphone", mic_labels,
                        si.default_mic.label if si.default_mic else mic_labels[0])
    mon_var = add_combo("System audio", mon_labels,
                        si.default_monitor.label if si.default_monitor else mon_labels[0])

    # output dir
    ttk.Label(frm, text="Output folder").grid(row=row, column=0, sticky="w", **pad)
    out_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Videos"))
    out_frame = ttk.Frame(frm)
    out_frame.grid(row=row, column=1, sticky="ew", **pad)
    out_frame.columnconfigure(0, weight=1)
    ttk.Entry(out_frame, textvariable=out_var).grid(row=0, column=0, sticky="ew")
    ttk.Button(out_frame, text="…",
               command=lambda: out_var.set(filedialog.askdirectory() or out_var.get())
               ).grid(row=0, column=1, padx=(6, 0))
    row += 1

    sw_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="Force software encoding", variable=sw_var).grid(
        row=row, column=1, sticky="w", **pad)
    row += 1

    status_var = tk.StringVar(value="Ready.")
    ttk.Separator(frm).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8)
    row += 1
    status_lbl = ttk.Label(frm, textvariable=status_var, foreground="#0a0")
    status_lbl.grid(row=row, column=0, columnspan=2, sticky="w", **pad)
    row += 1

    btns = ttk.Frame(frm)
    btns.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    start_btn = ttk.Button(btns, text="● Start recording")
    stop_btn = ttk.Button(btns, text="■ Stop", state="disabled")
    start_btn.pack(side="left", padx=4)
    stop_btn.pack(side="left", padx=4)

    def find_dev(devs, label, fallback_monitor=False):
        d = next((x for x in devs if x.label == label), None)
        if d is None and label not in ("(none)", ""):
            d = AudioDevice(id=label, label=label, is_monitor=fallback_monitor)
        return d

    def do_start():
        spec = RecordSpec(
            mode=mode_var.get(),
            quality=quality_var.get(),
            codec=codec_var.get(),
            fps=int(fps_var.get()),
            out_dir=out_var.get(),
            audio_codec=acodec_var.get(),
            mic=find_dev(si.mics, mic_var.get()),
            monitor=find_dev(si.monitors, mon_var.get(), fallback_monitor=True),
            force_software=sw_var.get(),
        )
        try:
            cmd, out_path = build_command(si, spec)
        except SystemExit as e:  # build_command may die()
            messagebox.showerror(APP_NAME, f"Cannot start: {e}")
            return
        try:
            state["proc"] = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Failed to launch ffmpeg: {e}")
            return
        status_var.set(f"● Recording → {os.path.basename(out_path)}")
        status_lbl.configure(foreground="#c00")
        start_btn.configure(state="disabled")
        stop_btn.configure(state="normal")

    def do_stop():
        proc = state.get("proc")
        if proc:
            _graceful_stop(proc)
            state["proc"] = None
        status_var.set("Saved. Ready.")
        status_lbl.configure(foreground="#0a0")
        start_btn.configure(state="normal")
        stop_btn.configure(state="disabled")

    start_btn.configure(command=do_start)
    stop_btn.configure(command=do_stop)

    def on_close():
        if state.get("proc"):
            do_stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
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
