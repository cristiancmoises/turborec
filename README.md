# Turbo Recorder

### High-Quality Screen + Audio Recorder 

Turbo Recorder is a fast and reliable screen-recording script designed
for GNU/Linux systems running X11. It automatically detects your real
screen size, captures with high fidelity, upscales to 4K using Lanczos,
merges monitor + microphone audio, and encodes using VAAPI hardware
acceleration for extremely low CPU usage.

## Features

-   Auto-detects X11 screen resolution
-   4K Upscaling (Lanczos → VAAPI)
-   Hardware-accelerated H.264 encoding (h264_vaapi)
-   Lossless or near-lossless quality
-   96 kHz FLAC audio capture
-   Captures monitor + microphone audio
-   Stable queues, resampling, amix merge
-   Automatic directory creation
-   Timestamped filenames

## Requirements

-   FFmpeg with VAAPI support
-   xrandr or xdpyinfo
-   PulseAudio or PipeWire
-   VAAPI-capable GPU + drivers

## Installation

    chmod +x turborecorder

Optional:

    sudo mv turborecorder /usr/local/bin/

## Usage

    ./turborecorder

