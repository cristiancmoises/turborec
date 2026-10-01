#!/bin/sh
# Compress one uncompressed TAR payload. TAR preserves modes, links, and empty
# directories that ZUPT's native regular-file records do not carry.
set -eu

die() { printf '[build-zupt-archive] ERROR: %s\n' "$*" >&2; exit 1; }
[ "$#" -eq 2 ] || die "usage: $0 input.tar output.zupt"
PAYLOAD="$1"
OUTPUT="$2"
case "${PAYLOAD}" in *.tar) ;; *) die "payload must be an uncompressed .tar" ;; esac
case "${OUTPUT}" in *.zupt) ;; *) die "output must use the .zupt extension" ;; esac
if [ ! -f "${PAYLOAD}" ] || [ ! -s "${PAYLOAD}" ]; then
    die "missing or empty TAR payload"
fi
command -v zupt >/dev/null 2>&1 || die "zupt is required (see packaging/install-zupt.sh)"
THREADS="${ZUPT_THREADS:-2}"
case "${THREADS}" in
    [1-9]|[1-5][0-9]|6[0-4]) ;;
    *) die "ZUPT_THREADS must be 1-64" ;;
esac

OUTPUT_DIR="$(dirname -- "${OUTPUT}")"
mkdir -p -- "${OUTPUT_DIR}"
OUTPUT_DIR="$(cd -- "${OUTPUT_DIR}" && pwd -P)"
OUTPUT="${OUTPUT_DIR}/$(basename -- "${OUTPUT}")"
# ZUPT pins output parents by opening every absolute ancestor for reading. A
# destination may legitimately sit below a search-only ancestor (such as
# /home), so compress/validate in private TMPDIR space, not beside that output.
WORK="$(mktemp -d "${TMPDIR:-/tmp}/turborec-zupt-build.XXXXXX")"
PUBLISH_WORK=""
cleanup() {
    rm -rf -- "${WORK}"
    if [ -n "${PUBLISH_WORK}" ]; then rm -rf -- "${PUBLISH_WORK}"; fi
}
trap cleanup EXIT INT HUP TERM
NAME="$(basename -- "${PAYLOAD}")"
cp -- "${PAYLOAD}" "${WORK}/${NAME}"
(
    cd -- "${WORK}"
    zupt compress -l 9 --lzhp -t "${THREADS}" archive.zupt "${NAME}"
    zupt test archive.zupt
    zupt extract -o verified archive.zupt
    cmp -- "${NAME}" "verified/${NAME}"
) >&2
# Copy verified bytes to a private directory on the destination filesystem;
# the last rename remains atomic even when TMPDIR lives on another mount.
PUBLISH_WORK="$(mktemp -d "${OUTPUT_DIR}/.zupt-build.XXXXXX")"
cp -- "${WORK}/archive.zupt" "${PUBLISH_WORK}/archive.zupt"
cmp -- "${WORK}/archive.zupt" "${PUBLISH_WORK}/archive.zupt"
mv -f -- "${PUBLISH_WORK}/archive.zupt" "${OUTPUT}"
printf '%s\n' "${OUTPUT}"
