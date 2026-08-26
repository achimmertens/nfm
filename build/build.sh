#!/usr/bin/env bash
# Build the NFM ARM64 image with an automatically resolved, commit-traceable
# version baked in. Run from the repo root or anywhere:
#     bash build/build.sh
# The version = "<git describe --tags --always --dirty>-<build-timestamp>",
# e.g. "v0.4.4-1-g95eb31a-20260826-1330", and is written to /app/VERSION in the
# image. main.py reads it at runtime for the visible page version.
set -euo pipefail

# Always resolve from the repo root, even when invoked from a subdirectory.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Build on disk, not on the small tmpfs (/tmp is only ~4G on the Pi and podman
# stores build blobs there -> "no space left on device" + lost layer cache on
# large rebuilds). Use $TMPDIR if the caller set one, otherwise fall back to a
# dedicated dir on the root filesystem. Overridable via env.
: "${TMPDIR:=${REPO_ROOT}/../podman-tmp}"
TMPDIR_BUILD="${TMPDIR}"
mkdir -p "${TMPDIR_BUILD}"
export TMPDIR="${TMPDIR_BUILD}"
echo ">>> Build TMPDIR: ${TMPDIR_BUILD}"

if ! command -v git >/dev/null 2>&1; then
    echo "ERROR: git not found on build host - required for version traceability." >&2
    exit 1
fi

GIT_DESCRIBE="$(git describe --tags --always --dirty 2>/dev/null || echo 'unknown')"
GIT_DATE="$(date +%Y-%m-%d_%H%M%S)"
GIT_VERSION="${GIT_DESCRIBE}-${GIT_DATE}"
echo ">>> Building NFM with version: ${GIT_VERSION}"

podman build \
    --build-arg GIT_VERSION="${GIT_VERSION}" \
    -f build/Dockerfile \
    -t localhost/nfm-arm64:latest \
    .

echo ">>> Build done. Image localhost/nfm-arm64:latest now carries version ${GIT_VERSION}"