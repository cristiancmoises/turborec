# Debian packaging for Turbo Recorder

This directory builds `dist/turborec_3.1.0_all.deb`.

## Layout

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
3. Emits `dist/turborec_3.1.0_all.deb`.

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

`ffmpeg`, `python3 (>= 3.8)`, and Tk. On Debian/Ubuntu Tk comes from
`python3-tk` (the `.deb` declares `Depends: ffmpeg, python3 (>= 3.8), python3-tk`).
On RPM distributions the equivalent is `python3-tkinter`.

## Verify a built package

```bash
# inspect members and metadata without installing
ar t dist/turborec_3.1.0_all.deb
mkdir -p /tmp/deb && ar x dist/turborec_3.1.0_all.deb --output /tmp/deb
tar -tvf /tmp/deb/data.tar.xz
tar -xOf /tmp/deb/control.tar.gz ./control
```
