# Turbo Recorder

### High-Quality Screen + Audio Recorder 

Turbo Recorder is a fast and reliable screen-recording script designed
for GNU/Linux systems running X11. It automatically detects your real
screen size, captures with high fidelity,
merges monitor + microphone audio, and encodes using VAAPI hardware
acceleration for extremely low CPU usage.

# PROJECT MOVED TO MY OWN FORGEJO INSTANCE!!! [ CHECK HERE ](https://git.securityops.co/securityops/turborec)

# [Sample here](https://youtu.be/mlf531Da9Qo?si=RTaSB9dJ4NSbGsOm)

<img width="1223" height="262" alt="2025-12-16_20-47" src="https://github.com/user-attachments/assets/d3d35f33-1b65-4c59-85ce-f6d9a10caea5" />

## Features

-   Auto-detects X11 screen resolution
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

    

