#!/usr/bin/env bash
# Build the remora-sandbox Docker image.
#
# Usage:
#   ./build.sh              # builds remora-sandbox:latest
#   ./build.sh --no-cache   # full rebuild

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="remora-sandbox"
IMAGE_TAG="latest"

echo "Building ${IMAGE_NAME}:${IMAGE_TAG} from ${SCRIPT_DIR}..."
echo ""

docker build \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -f "${SCRIPT_DIR}/Dockerfile" \
    "$@" \
    "${SCRIPT_DIR}"

echo ""
echo "Build complete: ${IMAGE_NAME}:${IMAGE_TAG}"
echo ""
echo "Test with:"
echo "  docker run --rm ${IMAGE_NAME}:${IMAGE_TAG} python -c \"print('hello from sandbox')\""
echo "  docker run --rm -v \$(pwd):/workspace ${IMAGE_NAME}:${IMAGE_TAG} pytest -q"
