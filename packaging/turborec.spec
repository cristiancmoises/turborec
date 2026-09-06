Name:           turborec
Version:        3.9.1
Release:        1%{?dist}
Summary:        State-of-the-art hardware-accelerated screen and audio recorder

License:        GPL-3.0-only
URL:            https://github.com/cristiancmoises/turborec
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

# Build-time tooling: rasterize the scalable icon and validate the desktop entry.
BuildRequires:  librsvg2-tools
BuildRequires:  desktop-file-utils
BuildRequires:  python3 >= 3.8

# Provider-neutral executable dependency: Fedora's ffmpeg-free and the full
# FFmpeg packages used by other RPM distributions all provide this path.
Requires:       /usr/bin/ffmpeg
Requires:       python3 >= 3.8
Requires:       python3-tkinter
Requires:       pulseaudio-utils
Recommends:     wf-recorder

%description
Turbo Recorder captures your screen and audio at the best quality your
hardware can deliver. It probes the machine and configures everything for
you: operating system, display server, CPU vendor, GPU, the best available
hardware video encoder (NVIDIA NVENC, Intel QSV, VAAPI, AMD AMF, Apple
VideoToolbox, x264, or OpenH264), screen resolution, and microphone / system-audio
sources. It then builds a quality-first FFmpeg pipeline and records.

Two front-ends share one engine:
  * turborec      - cross-platform CLI + GUI (Python, stdlib only)
  * turborecorder - fast, dependency-light Bash CLI for Linux/X11

%prep
%setup -q

%build
# Generate the 256x256 raster icon from the scalable SVG source.
rsvg-convert -w 256 -h 256 packaging/turborec.svg -o turborec-256.png

%check
python3 -m unittest discover -s tests -v

%install
rm -rf %{buildroot}

# Executables.
install -D -m 0755 turborec.py    %{buildroot}%{_bindir}/turborec
install -D -m 0755 turborecorder  %{buildroot}%{_bindir}/turborecorder

# Desktop entry.
install -D -m 0644 packaging/turborec.desktop \
        %{buildroot}%{_datadir}/applications/%{name}.desktop

# Icons: scalable SVG and generated 256x256 PNG.
install -D -m 0644 packaging/turborec.svg \
        %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{name}.svg
install -D -m 0644 turborec-256.png \
        %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/%{name}.png

# Documentation.
install -D -m 0644 README.md %{buildroot}%{_docdir}/%{name}/README.md
install -D -m 0644 docs/TUTORIAL.md \
        %{buildroot}%{_docdir}/%{name}/docs/TUTORIAL.md
install -D -m 0644 docs/README.pt-BR.md \
        %{buildroot}%{_docdir}/%{name}/docs/README.pt-BR.md

# Validate the installed desktop entry.
desktop-file-validate %{buildroot}%{_datadir}/applications/%{name}.desktop

%files
%license LICENSE
%doc %{_docdir}/%{name}/README.md
%doc %{_docdir}/%{name}/docs/TUTORIAL.md
%doc %{_docdir}/%{name}/docs/README.pt-BR.md
%{_bindir}/turborec
%{_bindir}/turborecorder
%{_datadir}/applications/%{name}.desktop
%{_datadir}/icons/hicolor/scalable/apps/%{name}.svg
%{_datadir}/icons/hicolor/256x256/apps/%{name}.png

%changelog
* Sun Sep 06 2026 Cristian Cezar Moises <ethicalhacker@riseup.net> - 3.9.1-1
- Add native BSD platform identities, X11/XWayland capture, sndio/OSS audio,
  and FreeBSD package smoke coverage.
- Fall back from x264 to a runtime-verified OpenH264 encoder for Fedora's
  ffmpeg-free builds, rejecting the unusable noopenh264 shim.
- Ship a deterministic complete source archive and a Tk-enabled Guix package.

* Sun Sep 06 2026 Cristian Cezar Moises <ethicalhacker@riseup.net> - 3.9.0-1
- Default the GUI, CLI, and configuration model to best quality, automatic
  codec selection, 23 fps, and 4K output.
- Prefer usable hardware AV1, then HEVC and H.264, with a real-time software
  H.264 fallback; keep RTMP streaming on compatible H.264.
- Keep English and Brazilian Portuguese documentation synchronized.

* Mon Aug 31 2026 Cristian Cezar Moises <ethicalhacker@riseup.net> - 3.8.1-1
- Recordings started in the same second no longer silently overwrite each
  other (ffmpeg -y): output filenames get a _1, _2, ... suffix on collision.
- publish-release.sh verifies each forge's git tag ref matches the local tag
  before publishing, defending against stale force-mirrors that delete tags.
- CI actions upgraded to Node-24 runtimes (checkout v6, artifacts v5).

* Mon Aug 31 2026 Cristian Cezar Moises <ethicalhacker@riseup.net> - 3.8.0-1
- Windows setup.exe installer now bundles Python 3.12 (with Tk) + FFmpeg and
  installs Python silently only when a Python 3.8+ with Tk is not present;
  the target machine needs no prerequisites.
- Fixed a shellcheck finding (SC2015) in build-windows.sh.

* Mon Aug 31 2026 Cristian Cezar Moises <ethicalhacker@riseup.net> - 3.7.1-1
- --duration now parses "1h30" as 1 hour 30 minutes (hour-minute shorthand).
- Bare trailing numbers still mean seconds (90, 1m30, 1h30s); all documented
  forms (90s, 5m, 1h30m, HH:MM:SS) are unchanged.

* Fri Jul 24 2026 Cristian Cezar Moises <ethicalhacker@riseup.net> - 3.7.0-1
- Repair Windows DirectShow microphone/camera discovery with stable UTF-8 IDs.
- Add native Windows monitor/window targets and correct macOS display selection.
- Add safe automatic capture modes and cross-platform regression tests.

* Mon Jul 13 2026 Cristian Cezar Moises <ethicalhacker@riseup.net> - 3.6.0-1
- Adaptive, resolution-aware encoder tuning for higher quality at each resolution.
- OBS-style YouTube live streaming (RTMP/RTMPS) via a stream key.
- Stream keys are redacted from all output and previews.

* Sat Jun 13 2026 Cristian Cezar Moises <ethicalhacker@riseup.net> - 3.2.0-1
- Initial RPM packaging of Turbo Recorder.
- Installs the turborec (Python CLI/GUI) and turborecorder (Bash CLI) front-ends.
- Ships desktop entry, scalable SVG icon, and generated 256x256 PNG icon.
