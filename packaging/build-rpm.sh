#!/usr/bin/env bash
#
# build-rpm.sh - build the turborec RPM from a freshly assembled source tarball.
#
# Usage:
#   packaging/build-rpm.sh
#
# Produces the binary (and source) RPMs under an rpmbuild tree inside ./build/,
# then copies the resulting packages into ./dist/.
#
set -euo pipefail

# --- Locate the repository root (this script lives in <root>/packaging). -----
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

# --- Package metadata (kept in sync with the spec). --------------------------
NAME="turborec"
SPEC="${SCRIPT_DIR}/${NAME}.spec"

VERSION="$(awk '/^Version:/ { print $2; exit }' "${SPEC}")"
if [ -z "${VERSION}" ]; then
    echo "error: could not read Version from ${SPEC}" >&2
    exit 1
fi

PKG="${NAME}-${VERSION}"

# --- Working directories. ----------------------------------------------------
BUILD_DIR="${REPO_ROOT}/build"
DIST_DIR="${REPO_ROOT}/dist"
RPMBUILD_DIR="${BUILD_DIR}/rpmbuild"
STAGE_DIR="${BUILD_DIR}/${PKG}"

rm -rf "${BUILD_DIR}"
mkdir -p "${RPMBUILD_DIR}"/{BUILD,BUILDROOT,RPMS,SRPMS,SOURCES,SPECS}
mkdir -p "${STAGE_DIR}/packaging"
mkdir -p "${DIST_DIR}"

# --- Assemble the source tree to be tarred. ----------------------------------
# These files are expected to exist at the repository root.
for f in turborec.py turborecorder README.md LICENSE; do
    cp -p "${REPO_ROOT}/${f}" "${STAGE_DIR}/${f}"
done

for f in turborec.desktop turborec.svg; do
    cp -p "${SCRIPT_DIR}/${f}" "${STAGE_DIR}/packaging/${f}"
done

# --- Create the source tarball with the expected %{name}-%{version} prefix. --
TARBALL="${RPMBUILD_DIR}/SOURCES/${PKG}.tar.gz"
tar -czf "${TARBALL}" -C "${BUILD_DIR}" "${PKG}"

# --- Build. ------------------------------------------------------------------
cp -p "${SPEC}" "${RPMBUILD_DIR}/SPECS/"

# --nodeps: skip the build-time BuildRequires check. The actual tools
# (rsvg-convert, desktop-file-validate) are installed via the host's package
# manager, but on a non-RPM build host the RPM database doesn't know that.
# Runtime "Requires:" in the package metadata are unaffected.
rpmbuild \
    --define "_topdir ${RPMBUILD_DIR}" \
    --nodeps \
    -ba "${RPMBUILD_DIR}/SPECS/$(basename "${SPEC}")"

# --- Collect the artifacts. --------------------------------------------------
find "${RPMBUILD_DIR}/RPMS" -name '*.rpm' -exec cp -p {} "${DIST_DIR}/" \;
find "${RPMBUILD_DIR}/SRPMS" -name '*.rpm' -exec cp -p {} "${DIST_DIR}/" \;

echo
echo "Build complete. Packages copied to: ${DIST_DIR}"
ls -1 "${DIST_DIR}"
