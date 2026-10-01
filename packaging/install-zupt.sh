#!/bin/sh
# Build the official pinned source in private scratch space, without optional
# SDKs or downloaded/precompiled libraries. No elevated installation required.
# Usage: packaging/install-zupt.sh /absolute/path/to/bin
set -eu

die() { printf '[install-zupt] ERROR: %s\n' "$*" >&2; exit 1; }
[ "$#" -eq 1 ] || die "usage: $0 /absolute/path/to/bin"
DESTINATION="$1"
case "${DESTINATION}" in /*/*) ;; *) die "destination must be an absolute bin directory" ;; esac
for tool in curl sha256sum tar make cc; do
    command -v "${tool}" >/dev/null 2>&1 || die "required tool not found: ${tool}"
done

ZUPT_VERSION="5.2.9"
ZUPT_COMMIT="63f27dd0c5afcf155f813a069c29f6384d46790c"
ZUPT_SHA256="ef3fbd30bbf64af93c04182d6579157179b9775d08a475b5d2b86dc13db9b73a"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/turborec-zupt.XXXXXX")"
trap 'rm -rf -- "${WORK}"' EXIT INT HUP TERM
curl -fL --retry 3 --connect-timeout 30 --max-time 180 \
    --proto '=https' --tlsv1.2 \
    -o "${WORK}/source.tar.gz" \
    "https://codeload.github.com/cristiancmoises/zupt/tar.gz/${ZUPT_COMMIT}"
printf '%s  %s\n' "${ZUPT_SHA256}" "${WORK}/source.tar.gz" | sha256sum -c -
tar -xzf "${WORK}/source.tar.gz" -C "${WORK}"
SOURCE="${WORK}/zupt-${ZUPT_COMMIT}"
make -C "${SOURCE}" -j2 WITH_SDK=0 WITH_PQBOX=0 WITH_JASMIN=0
"${SOURCE}/zupt" version | grep -Fx "zupt ${ZUPT_VERSION} (ZUPT)"
(
    cd -- "${SOURCE}"
    ./zupt compress -l 9 --lzhp -t 2 "${WORK}/smoke.zupt" LICENSE
    ./zupt test "${WORK}/smoke.zupt"
    ./zupt extract -o "${WORK}/smoke" "${WORK}/smoke.zupt"
    cmp LICENSE "${WORK}/smoke/LICENSE"
)
mkdir -p -- "${DESTINATION}"
install -m 0755 "${SOURCE}/zupt" "${DESTINATION}/zupt"
printf '[install-zupt] Installed ZUPT %s (%s) in %s\n' \
    "${ZUPT_VERSION}" "${ZUPT_COMMIT}" "${DESTINATION}" >&2
