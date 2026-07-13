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
#         packaging/publish-release.sh v3.6.0 [asset-dir]
#
#   - <tag>       the release tag, e.g. v3.6.0 (must already be pushed).
#   - [asset-dir] a directory of files to attach. If omitted, the assets are
#                 downloaded from the GitHub release for <tag> using `gh`.
#
#  Tokens are read ONLY from the environment (never hard-coded / never printed):
#     FJTOKEN — Forgejo API token (git.securityops.co). Skips Forgejo if unset.
#     CBTOKEN — Codeberg API token.                     Skips Codeberg if unset.
#
#  Idempotent: reuses an existing release for the tag and skips any asset already
#  attached, so it is safe to re-run.
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

log()  { printf '[publish] %s\n' "$*" >&2; }
die()  { printf '[publish] ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "required tool not found: $1"; }

need curl
need python3

TAG="${1:-}"
[ -n "${TAG}" ] || die "usage: FJTOKEN=… CBTOKEN=… $0 <tag> [asset-dir]"
ASSET_DIR="${2:-}"

# ---- gather the assets ------------------------------------------------------
CLEANUP_DIR=""
if [ -z "${ASSET_DIR}" ]; then
    need gh
    ASSET_DIR="$(mktemp -d "${TMPDIR:-/tmp}/turborec-assets.XXXXXX")"
    CLEANUP_DIR="${ASSET_DIR}"
    log "downloading ${TAG} assets from the GitHub release…"
    gh release download "${TAG}" -D "${ASSET_DIR}"
fi
[ -d "${ASSET_DIR}" ] || die "asset dir not found: ${ASSET_DIR}"
trap '[ -n "${CLEANUP_DIR}" ] && rm -rf -- "${CLEANUP_DIR}"' EXIT

# Collect the files to publish (regular files only).
ASSETS=()
while IFS= read -r f; do ASSETS+=("$f"); done < <(find "${ASSET_DIR}" -maxdepth 1 -type f | LC_ALL=C sort)
[ "${#ASSETS[@]}" -gt 0 ] || die "no asset files in ${ASSET_DIR}"
log "found ${#ASSETS[@]} asset(s) to publish for ${TAG}"

# ---- release notes: reuse the GitHub release body when available ------------
NOTES=""
if command -v gh >/dev/null 2>&1; then
    NOTES="$(gh release view "${TAG}" --json body --jq '.body' 2>/dev/null || true)"
fi
[ -n "${NOTES}" ] || NOTES="Turbo Recorder ${TAG}"

# ---- helper: publish to one Gitea/Forgejo-family forge ----------------------
# args: <label> <api-base> <owner> <token>
publish_to() {
    local label="$1" api="$2" owner="$3" token="$4"
    local base="${api}/repos/${owner}/${REPO}"
    local auth="Authorization: token ${token}"

    log "── ${label} ────────────────────────────────────────────"

    # Some repos ship with the Releases unit disabled (creation then fails with a
    # misleading "target couldn't be found"); enable it (idempotent, needs admin).
    curl -fsS -X PATCH -H "${auth}" -H "Content-Type: application/json" \
         -d '{"has_releases":true}' "${base}" >/dev/null 2>&1 || true

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
        [ -n "${rid}" ] || { log "${label}: could not create release — skipping"; return 1; }
        log "${label}: created release id=${rid}"
    else
        log "${label}: reusing release id=${rid}"
    fi

    # Which asset names are already attached (so re-runs skip them)?
    local existing
    existing="$(curl -fsS -H "${auth}" "${base}/releases/${rid}" \
               | python3 -c 'import sys,json;print("\n".join(a["name"] for a in json.load(sys.stdin).get("assets",[])))' 2>/dev/null || true)"

    local f name code
    for f in "${ASSETS[@]}"; do
        name="$(basename "${f}")"
        if printf '%s\n' "${existing}" | grep -qxF "${name}"; then
            log "  = ${name} (already present, skipped)"
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
            log "  ! ${name} FAILED (HTTP ${code}) — continuing"
        fi
    done
}

# ---- run for each forge that has a token ------------------------------------
did_any=0
if [ -n "${FJTOKEN:-}" ]; then publish_to "Forgejo (primary)" "${FORGEJO_API}" "${FORGEJO_OWNER}" "${FJTOKEN}"; did_any=1
else log "FJTOKEN not set — skipping Forgejo"; fi
if [ -n "${CBTOKEN:-}" ]; then publish_to "Codeberg" "${CODEBERG_API}" "${CODEBERG_OWNER}" "${CBTOKEN}"; did_any=1
else log "CBTOKEN not set — skipping Codeberg"; fi

[ "${did_any}" = "1" ] || die "no forge tokens set (FJTOKEN / CBTOKEN) — nothing to do"
log "done."
