#!/usr/bin/env bash
# =============================================================================
#  publish-release.sh — mirror a release's binaries onto the Forgejo (primary)
#  and Codeberg forges.
#
#  Why this exists: Forgejo is the source of truth and GitHub + Codeberg are
#  push-mirrors, but Forgejo/Gitea push-mirrors replicate only git refs
#  (branches/tags) — NOT release objects or their binary assets. GitHub gets its
#  binaries from the release.yml GitHub Actions build; this script attaches the
#  same binaries to the matching Forgejo and Codeberg releases so all three
#  forges carry the full set.
#
#  Usage:
#     FJTOKEN=<forgejo-token> CBTOKEN=<codeberg-token> \
#         packaging/publish-release.sh v3.7.0 [asset-dir]
#
#   - <tag>       the release tag, e.g. v3.7.0 (must already be pushed).
#   - [asset-dir] a directory of files to attach. If omitted, the assets are
#                 downloaded from the GitHub release for <tag> using `gh`.
#
#  Tokens are read ONLY from the environment (never hard-coded / never printed):
#     FJTOKEN — Forgejo API token (git.securityops.co). Skips Forgejo if unset.
#     CBTOKEN — Codeberg API token.                     Skips Codeberg if unset.
#
#  Idempotent: reuses an existing release for the tag and skips any asset already
#  attached with the same byte size, so it is safe to re-run. Missing binaries,
#  size mismatches, API errors, and failed uploads make the command fail.
#
#  Requires: curl, python3 (both), and gh (only when auto-downloading assets).
#  License: GPL-3.0.
# =============================================================================
set -euo pipefail

# ---- forge coordinates (this project's actual setup) ------------------------
FORGEJO_API="https://git.securityops.co/api/v1"
FORGEJO_OWNER="cristiancmoises"
CODEBERG_API="https://codeberg.org/api/v1"
CODEBERG_OWNER="berkeley"
REPO="turborec"
GITHUB_REPO="cristiancmoises/turborec"

log()  { printf '[publish] %s\n' "$*" >&2; }
die()  { printf '[publish] ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "required tool not found: $1"; }

need curl
need python3

TAG="${1:-}"
[ -n "${TAG}" ] || die "usage: FJTOKEN=… CBTOKEN=… $0 <tag> [asset-dir]"
VERSION="${TAG#v}"
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || die "tag must look like v3.7.0 (got: ${TAG})"
ASSET_DIR="${2:-}"

# ---- gather the assets ------------------------------------------------------
CLEANUP_DIR=""
if [ -z "${ASSET_DIR}" ]; then
    need gh
    ASSET_DIR="$(mktemp -d "${TMPDIR:-/tmp}/turborec-assets.XXXXXX")"
    CLEANUP_DIR="${ASSET_DIR}"
    log "downloading ${TAG} assets from the GitHub release…"
    gh release download "${TAG}" --repo "${GITHUB_REPO}" -D "${ASSET_DIR}"
fi
[ -d "${ASSET_DIR}" ] || die "asset dir not found: ${ASSET_DIR}"
trap '[ -n "${CLEANUP_DIR}" ] && rm -rf -- "${CLEANUP_DIR}"' EXIT

# Collect the files to publish (regular files only).
ASSETS=()
while IFS= read -r f; do ASSETS+=("$f"); done < <(find "${ASSET_DIR}" -maxdepth 1 -type f | LC_ALL=C sort)
[ "${#ASSETS[@]}" -gt 0 ] || die "no asset files in ${ASSET_DIR}"
log "found ${#ASSETS[@]} asset(s) to publish for ${TAG}"

# Every supported binary/package must exist and be non-empty. SHA256SUMS and
# other non-binary release files are allowed and mirrored too.
EXPECTED=(
    "Turbo_Recorder-${VERSION}-windows-x64.exe"
    "Turbo_Recorder-${VERSION}-x86_64.AppImage"
    "turborec-${VERSION}-1.noarch.rpm"
    "turborec-${VERSION}-1.src.rpm"
    "turborec-${VERSION}-guix-x86_64.tar.gz"
    "turborec-${VERSION}.pkg"
    "turborec-${VERSION}.tar.gz"
    "turborec_${VERSION}_all.deb"
)
for name in "${EXPECTED[@]}"; do
    [ -s "${ASSET_DIR}/${name}" ] || die "missing or empty required asset: ${name}"
done

# ---- release notes: reuse the GitHub release body when available ------------
NOTES=""
if command -v gh >/dev/null 2>&1; then
    NOTES="$(gh release view "${TAG}" --repo "${GITHUB_REPO}" \
             --json body --jq '.body' 2>/dev/null || true)"
fi
[ -n "${NOTES}" ] || NOTES="Turbo Recorder ${TAG}"

# ---- helper: publish to one Gitea/Forgejo-family forge ----------------------
# args: <label> <api-base> <owner> <token>
publish_to() {
    local label="$1" api="$2" owner="$3" token="$4"
    local base="${api}/repos/${owner}/${REPO}"
    local auth="Authorization: token ${token}"

    log "── ${label} ────────────────────────────────────────────"

    # Reuse an existing release for the tag, else create one.
    local rid
    rid="$(curl -fsS -H "${auth}" "${base}/releases/tags/${TAG}" 2>/dev/null \
           | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)"
    if [ -z "${rid}" ]; then
        local payload
        payload="$(NOTES="${NOTES}" TAG="${TAG}" python3 -c \
          'import os,json;print(json.dumps({"tag_name":os.environ["TAG"],"name":"Turbo Recorder "+os.environ["TAG"].lstrip("v"),"body":os.environ["NOTES"],"draft":False,"prerelease":False}))')"
        rid="$(curl -fsS -X POST -H "${auth}" -H "Content-Type: application/json" \
               -d "${payload}" "${base}/releases" \
               | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d.get("id") or "")')"
        [ -n "${rid}" ] || {
            log "${label}: could not create release"
            return 1
        }
        log "${label}: created release id=${rid}"
    else
        log "${label}: reusing release id=${rid}"
    fi

    # Existing name/size pairs let re-runs skip verified assets while rejecting
    # a stale or truncated upload with the same name.
    local existing
    existing="$(curl -fsS -H "${auth}" "${base}/releases/${rid}" \
               | python3 -c 'import sys,json;print("\n".join("{}\t{}".format(a["name"],a.get("size",0)) for a in json.load(sys.stdin).get("assets",[])))' 2>/dev/null || true)"

    local f name code local_size remote_size failures=0
    for f in "${ASSETS[@]}"; do
        name="$(basename "${f}")"
        local_size="$(wc -c < "${f}" | tr -d '[:space:]')"
        remote_size="$(printf '%s\n' "${existing}" \
            | awk -F '\t' -v wanted="${name}" '$1 == wanted { print $2; exit }')"
        if [ -n "${remote_size}" ]; then
            if [ "${remote_size}" = "${local_size}" ]; then
                log "  = ${name} (already present and size verified)"
                continue
            fi
            log "  ! ${name} has remote size ${remote_size}, expected ${local_size}"
            failures=$((failures + 1))
            continue
        fi
        # --http1.1 avoids HTTP/2 framing errors some servers hit on large
        # uploads; a failed upload must not abort the whole run (|| code=000),
        # so remaining assets and the other forge still get published.
        code="$(curl -s -o /dev/null -w '%{http_code}' --http1.1 --max-time 3600 \
               -X POST -H "${auth}" \
               -F "attachment=@${f};filename=${name}" \
               "${base}/releases/${rid}/assets?name=${name}")" || code="000"
        if [ "${code}" = "201" ]; then
            log "  + ${name}"
        else
            log "  ! ${name} FAILED (HTTP ${code})"
            failures=$((failures + 1))
        fi
    done

    # Re-read the release and prove that every local file exists remotely at
    # the same size. This also catches servers that return success prematurely.
    existing="$(curl -fsS -H "${auth}" "${base}/releases/${rid}" \
               | python3 -c 'import sys,json;print("\n".join("{}\t{}".format(a["name"],a.get("size",0)) for a in json.load(sys.stdin).get("assets",[])))' 2>/dev/null || true)"
    for f in "${ASSETS[@]}"; do
        name="$(basename "${f}")"
        local_size="$(wc -c < "${f}" | tr -d '[:space:]')"
        remote_size="$(printf '%s\n' "${existing}" \
            | awk -F '\t' -v wanted="${name}" '$1 == wanted { print $2; exit }')"
        if [ "${remote_size:-missing}" != "${local_size}" ]; then
            log "  ! verification failed for ${name}"
            failures=$((failures + 1))
        fi
    done
    [ "${failures}" -eq 0 ]
}

# ---- run for each forge that has a token ------------------------------------
did_any=0
failed=0
if [ -n "${FJTOKEN:-}" ]; then
    if ! publish_to "Forgejo (primary)" "${FORGEJO_API}" "${FORGEJO_OWNER}" "${FJTOKEN}"; then
        failed=1
    fi
    did_any=1
else log "FJTOKEN not set — skipping Forgejo"; fi
if [ -n "${CBTOKEN:-}" ]; then
    if ! publish_to "Codeberg" "${CODEBERG_API}" "${CODEBERG_OWNER}" "${CBTOKEN}"; then
        failed=1
    fi
    did_any=1
else log "CBTOKEN not set — skipping Codeberg"; fi

[ "${did_any}" = "1" ] || die "no forge tokens set (FJTOKEN / CBTOKEN) — nothing to do"
[ "${failed}" = "0" ] || die "one or more forge uploads failed verification"
log "done."
