# Packaging for Turbo Recorder

This directory builds every distributable: the Debian `.deb`, the RPM, the
AppImage, a portable `.zupt` archive for **any Unix (including the BSDs)**, and a native
**FreeBSD `.pkg`**.

Every release also publishes `turborec-<version>-source.zupt`: an immutable
archive of the complete release source, including tests. Its tar payload uses
deterministic metadata; the outer ZUPT container need not be byte-reproducible. Use
it for distribution packaging; `turborec-<version>.zupt` is the portable
end-user installer. Native `.deb`, binary/source RPM, AppImage, FreeBSD `.pkg`
and Windows EXE/installer formats remain available.

The portable, complete-source and Guix `.zupt` distributions each contain one
**uncompressed tar payload**, preserving Unix modes and symlinks through tar.
Use the reader from the [official ZUPT releases](https://github.com/cristiancmoises/zupt/releases),
verify `SHA256SUMS`, extract with `zupt`, then extract the tar. Standard tar does
not understand `.zupt` directly. Do not put gzip-compressed tar files inside
these release archives.

Archive builders require Python 3 for exact-leaf atomic publication in addition
to ZUPT and tar. Automatically downloaded or cached appimagetool binaries need
a valid SHA-256 pin and either `sha256sum` or `shasum`; missing verification is
an error, never a warning-only bypass. For architectures other than the pinned
x86_64 release, supply the correct `APPIMAGETOOL_SHA256` or explicitly choose an
operator-trusted `APPIMAGETOOL`/PATH binary. Keep build/cache folders private.

`turborec.py`'s `VERSION` is the release source of truth. The portable and
FreeBSD builders derive it automatically; package formats that require literal
metadata are checked against it by `tests/test_release_metadata.py`. The GitHub
Actions release workflow builds the Linux artifacts on
`ubuntu-latest` and the FreeBSD `.pkg` in a real FreeBSD VM
(`vmactions/freebsd-vm`), then attaches all of them to the tagged release.

## Windows builder

- **`build-windows.sh`** → `dist/Turbo_Recorder-<version>-windows-x64-setup.exe`.
  Downloads and SHA-256-verifies two pinned artifacts: the gyan.dev static
  FFmpeg build and the **python.org Python 3.12 installer**, then runs `makensis`.
  The resulting installer ships `turborec.py`, FFmpeg **and** the Python 3.12
  installer; during install it runs Python silently per-user (with Tk and the
  `py` launcher) only when no Python 3.8+ with Tk is already present — so the
  target machine needs **no prerequisites**. The uninstaller removes the app but
  never uninstalls the shared Python.
  Setup 3.10.2 is non-elevated: app files live in
  `%LOCALAPPDATA%\Programs\Turbo Recorder`, registry entries and shortcuts belong
  to the current user, and Python/its launcher are installed per-user. Discovery
  and launchers use Python isolated mode. Remove a legacy machine-wide install
  separately through Windows Settings before switching; do not remove shared Python.

## BSD / portable builders

- **`build-tarball.sh`** → `dist/turborec-<version>.zupt`, containing
  `turborec-<version>.tar`. Strict POSIX `sh`
  (no bashisms) so it runs under base `/bin/sh` on FreeBSD/OpenBSD/NetBSD as well
  as Linux/macOS. Unpacks to a self-contained tree with `install.sh` /
  `uninstall.sh` honouring `PREFIX` (default `/usr/local`) and `DESTDIR`:

  ```sh
  zupt extract -o unpack turborec-3.10.2.zupt
  tar xf unpack/turborec-3.10.2.tar
  cd turborec-3.10.2
  sudo ./install.sh                  # → /usr/local
  PREFIX="$HOME/.local" ./install.sh # per-user
  ```

- **`build-freebsd-pkg.sh`** → `dist/turborec-<version>.pkg`. Must run on FreeBSD
  (uses `pkg create`). Stages the tree under `${PREFIX}`, generates a plist +
  `+MANIFEST`, and emits a package installable with
  `pkg add ./turborec-3.10.2.pkg`. Runtime prerequisites (`python3`, `ffmpeg`,
  and Tk for the GUI) are documented in the package description rather than
  declared as hard deps, so the file installs cleanly on any FreeBSD release
  (`pkg install python3 ffmpeg`).

- **`build-source-tarball.sh`** → `dist/turborec-<version>-source.zupt`, containing
  `turborec-<version>-source.tar`. Archives release source from `HEAD` with
  deterministic metadata; it refuses staged or tracked working-tree edits so a
  release cannot omit uncommitted source accidentally. Prompts, local settings,
  credentials and private archives do not belong in release source payloads.

- **Guix release pack** → `turborec-<version>-guix-x86_64.zupt`, containing
  `turborec-<version>-guix-x86_64.tar`. Verify the release checksum before the
  privileged extraction of the Guix closure:

  ```sh
  zupt extract -o guix-unpack turborec-3.10.2-guix-x86_64.zupt
  sudo tar xf guix-unpack/turborec-3.10.2-guix-x86_64.tar -C /
  ```

## Publishing release binaries to Forgejo + Codeberg

Forgejo (`git.securityops.com.br`) is the primary repo; GitHub and Codeberg are
independent Git remotes synchronized deliberately during a release. Git pushes
replicate branches and tags but **not** release objects or their binaries.
GitHub builds its binaries via `release.yml`; to attach that same verified set
to the Forgejo and Codeberg releases, run:

```sh
# downloads the tag's assets from the GitHub release, then attaches them to the
# matching Forgejo + Codeberg releases (creating the release if needed)
FJTOKEN=<forgejo-token> CBTOKEN=<codeberg-token> \
    packaging/publish-release.sh v3.10.2

# or attach files from a local directory instead of downloading
FJTOKEN=… CBTOKEN=… packaging/publish-release.sh v3.10.2 dist/
```

Tokens are read only from the environment. The script requires all **10
payloads** (including both Windows executables, both RPMs and complete source),
and `SHA256SUMS`: **11 release assets in total**. It
mirrors the checksum file, validates each public download URL against the forge
origin, downloads every asset without sending credentials, and compares remote
bytes with the locally verified files. Equal name/size alone is not accepted.
Incomplete uploads or changed bytes fail; identical re-runs are idempotent.
Requires Bash, curl, Python 3 and `cmp`; `gh` is needed only for automatic
asset downloads. No GNU `find` or checksum utility is required by the publisher.

## Debian `.deb` layout

```
packaging/
├── build-deb.sh            # portable builder (dpkg-deb OR ar+tar+gzip+xz)
├── assets/
│   └── turborec.svg        # source icon (256x256 viewBox, scalable)
└── debian/
    ├── control             # package metadata + Depends
    ├── postinst            # refresh icon/desktop caches on install
    ├── postrm              # refresh icon/desktop caches on removal
    └── turborec.desktop    # desktop entry (Exec=turborec gui)
```

This package ships **no** configuration files, so there is no `conffiles`
member (the builder adds one only if `debian/conffiles` exists).

## Build

```bash
./packaging/build-deb.sh
```

The script:

1. Stages the install layout from the repo:
   - `turborec.py`   -> `/usr/bin/turborec`            (0755)
   - `turborecorder` -> `/usr/bin/turborecorder`       (0755)
   - `debian/turborec.desktop` -> `/usr/share/applications/turborec.desktop`
   - `assets/turborec.svg`     -> `/usr/share/icons/hicolor/scalable/apps/turborec.svg`
   - rasterized 256x256 PNG    -> `/usr/share/icons/hicolor/256x256/apps/turborec.png`
   - `README.md`               -> `/usr/share/doc/turborec/README.md`
2. Builds the control tree (`control` with computed `Installed-Size`,
   `md5sums`, `postinst`, `postrm`).
3. Emits `dist/turborec_3.10.2_all.deb`.

### dpkg-deb vs. portable mode

- If `dpkg-deb` is on `PATH`, it is used (`dpkg-deb --root-owner-group --build`).
- Otherwise the script assembles the `.deb` by hand using only `ar`, `tar`,
  `gzip` and `xz`, producing the three `ar` members in the required order:
  `debian-binary`, `control.tar.gz`, `data.tar.xz`.

### Icon rasterization

The PNG is generated from the SVG using the first available of
`rsvg-convert`, `inkscape`, or ImageMagick `convert`. If none is present but a
pre-rendered `assets/turborec.png` exists, that is used instead.

## Runtime dependencies

Version 3.10.2 keeps the established 11 release assets: `.deb`, binary and
source `.rpm`, AppImage, FreeBSD `.pkg`, Windows portable `.exe` and setup
`.exe`, portable/Guix/complete-source `.zupt`, plus `SHA256SUMS`. Each of the
three ZUPT assets holds one real uncompressed TAR payload; these are not
`.tar.gz` distributions.

Guix's packaged FFmpeg may lack NVENC. A usable hardware profile also requires
matching driver/runtime libraries. The recorder does not install drivers or
reboot; operators can use Auto/CPU or an already-installed compatible FFmpeg
with `turborec --ffmpeg /path/to/ffmpeg record` (global option before the
subcommand), or the JSON `ffmpeg` setting. Synthetic startup validation does
not establish physical-device support across all operating systems.

All non-self-contained builds need `ffmpeg`, Python 3.8+, and Tk for the GUI.
On Debian/Ubuntu Tk comes from `python3-tk`; the `.deb` also installs
`pulseaudio-utils` for Linux Pulse/PipeWire discovery. On RPM distributions Tk
is normally `python3-tkinter`; the RPM accepts any provider of
`/usr/bin/ffmpeg`, including Fedora's `ffmpeg-free`. When `libx264` is absent,
Turbo Recorder can use `libopenh264` only after its one-frame probe succeeds;
the `noopenh264` shim is rejected. With `fedora-cisco-openh264` enabled, repair
a stub installation with `sudo dnf swap noopenh264 openh264`.

BSD microphone discovery does not require PulseAudio: OpenBSD prefers an
FFmpeg sndio input, while FreeBSD, NetBSD and DragonFly prefer OSS. Each source
must be backed by a real character-device node. `pactl` is optional on BSD and
is needed only for available Pulse sources, including the monitor source
required for desktop/system audio. BSD screen capture uses X11/XWayland.

The Guix definition includes Python's `tk` output and validates `_tkinter`
during the build. This validates the intended CLI/GUI runtime composition in a
headless environment; it does not claim a visual GUI test.

## Verify a built package

```bash
# inspect members and metadata without installing
ar t dist/turborec_3.10.2_all.deb
mkdir -p /tmp/deb && ar x dist/turborec_3.10.2_all.deb --output /tmp/deb
tar -tvf /tmp/deb/data.tar.xz
tar -xOf /tmp/deb/control.tar.gz ./control
```
