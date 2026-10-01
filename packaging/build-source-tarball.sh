#!/bin/sh
# Build the immutable, distribution-friendly source archive published with a
# release. Unlike the portable Unix archive, this contains the complete tracked
# source tree, including tests and packaging metadata.
set -eu

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"
DIST_DIR="${REPO_ROOT}/dist"

log() { printf '[build-source-tarball] %s\n' "$*" >&2; }
die() { printf '[build-source-tarball] ERROR: %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "required tool not found: git"
command -v zupt >/dev/null 2>&1 || die "required tool not found: zupt"

git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || die "repository metadata is required"

# A source release must describe one exact commit. Refuse to silently omit
# uncommitted edits when somebody invokes the builder by hand.
git -C "${REPO_ROOT}" diff --quiet --ignore-submodules -- \
    || die "tracked working-tree changes are present; commit them first"
git -C "${REPO_ROOT}" diff --cached --quiet --ignore-submodules -- \
    || die "staged changes are present; commit them first"

PKG_VERSION="$(git -C "${REPO_ROOT}" show HEAD:turborec.py \
    | sed -n 's/^VERSION = "\(.*\)"/\1/p' | head -1)"
[ -n "${PKG_VERSION}" ] || die "could not read VERSION from HEAD:turborec.py"

TOP="turborec-${PKG_VERSION}"
OUT="${DIST_DIR}/${TOP}-source.zupt"
mkdir -p -- "${DIST_DIR}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/turborec-source.XXXXXX")"
trap 'rm -rf -- "${WORK}"' EXIT INT HUP TERM

# Tracked-only is necessary but not sufficient: ship product/build sources and
# the public guides, not agent instructions, plans, secrets, or arbitrary notes.
git -C "${REPO_ROOT}" ls-tree -r --name-only HEAD > "${WORK}/tracked"
set --
while IFS= read -r path; do
    lower="$(printf '%s' "${path}" | tr '[:upper:]' '[:lower:]')"
    case "${lower}" in
        *prompt*|*private*|*credential*|*secret*|*/plans/*|*/agents.md|*/claude.md|\
        agents.md|claude.md|*.key|*.pem|*/.*) continue ;;
    esac
    case "${path}" in
        turborec.py|turborecorder|guix.scm|LICENSE|.gitignore|\
        README.md|CHANGELOG.md|SECURITY.md|\
        docs/TUTORIAL.md|docs/README.pt-BR.md|docs/turborec-gui.png|\
        packaging/README.md|packaging/AppRun|packaging/debian/control|\
        packaging/debian/postinst|packaging/debian/postrm|\
        packaging/debian/preinst|packaging/debian/prerm|\
        packaging/*.sh|packaging/*.spec|packaging/*.nsi|packaging/*.cmd|\
        packaging/*.desktop|packaging/*.svg|packaging/*.ico|\
        tests/*.py|website/*.html|website/*.css|website/*.js|\
        website/*.xml|website/*.png|website/*.svg|website/*.ico|\
        .github/workflows/*.yml|.github/workflows/*.yaml|.github/dependabot.yml)
            set -- "$@" "${path}" ;;
    esac
done < "${WORK}/tracked"
[ "$#" -gt 0 ] || die "no distribution sources selected"

# git archive preserves modes/links and creates a reproducible TAR for one
# commit. The stock ZUPT envelope has a creation time and random archive UUID;
# reproducibility applies to the extracted TAR payload, not envelope bytes.
git -C "${REPO_ROOT}" archive --format=tar --prefix="${TOP}/" HEAD \
    --output="${WORK}/${TOP}-source.tar" -- "$@"
sh "${SCRIPT_DIR}/build-zupt-archive.sh" "${WORK}/${TOP}-source.tar" "${OUT}" >/dev/null

test -s "${OUT}" || die "archive is empty"
log "built: ${OUT}"
printf '%s\n' "${OUT}"
