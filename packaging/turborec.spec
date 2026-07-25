Name:           turborec
Version:        3.7.0
Release:        1%{?dist}
Summary:        State-of-the-art hardware-accelerated screen and audio recorder

License:        GPL-3.0-or-later
URL:            https://github.com/cristiancmoises/turborec
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

# Build-time tooling: rasterize the scalable icon and validate the desktop entry.
BuildRequires:  librsvg2-tools
BuildRequires:  desktop-file-utils

Requires:       ffmpeg
Requires:       python3 >= 3.8
Requires:       python3-tkinter
Requires:       pulseaudio-utils
Recommends:     wf-recorder

%description
Turbo Recorder captures your screen and audio at the best quality your
hardware can deliver. It probes the machine and configures everything for
you: operating system, display server, CPU vendor, GPU, the best available
hardware video encoder (NVIDIA NVENC, Intel QSV, VAAPI, AMD AMF, Apple
VideoToolbox, or x264), screen resolution, and microphone / system-audio
sources. It then builds a quality-first FFmpeg pipeline and records.

Two front-ends share one engine:
  * turborec      - cross-platform CLI + GUI (Python, stdlib only)
  * turborecorder - fast, dependency-light Bash CLI for Linux/X11

%prep
%setup -q

%build
# Generate the 256x256 raster icon from the scalable SVG source.
rsvg-convert -w 256 -h 256 packaging/turborec.svg -o turborec-256.png

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

%post
# Update the icon cache and the desktop database (non-fatal if missing).
touch --no-create %{_datadir}/icons/hicolor &>/dev/null || :
gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :
update-desktop-database &>/dev/null || :

%postun
if [ $1 -eq 0 ] ; then
    touch --no-create %{_datadir}/icons/hicolor &>/dev/null
    gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :
fi
update-desktop-database &>/dev/null || :

%posttrans
gtk-update-icon-cache %{_datadir}/icons/hicolor &>/dev/null || :

%changelog
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
