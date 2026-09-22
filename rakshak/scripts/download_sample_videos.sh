#!/usr/bin/env bash
# =============================================================================
# Download sample Indian traffic videos for device simulator testing.
#
# Sources: Publicly available sample videos from open datasets and repos.
# If any URL is unreachable, a warning is logged and the script continues.
#
# Usage:
#     bash scripts/download_sample_videos.sh
#
# Output directory: data/samples/
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SAMPLES_DIR="${PROJECT_ROOT}/data/samples"

mkdir -p "$SAMPLES_DIR"

# ---------------------------------------------------------------------------
# Video sources — public, freely available sample clips.
# These are short clips suitable for ANPR testing.
# ---------------------------------------------------------------------------

declare -A VIDEOS=(
    # Sample 1: Traffic footage from OpenCV samples
    ["sample1.mp4"]="https://raw.githubusercontent.com/opencv/opencv/master/samples/data/vtest.avi"
    # Sample 2: Short MP4 test video
    ["sample2.mp4"]="https://www.learningcontainer.com/wp-content/uploads/2020/05/sample-mp4-file.mp4"
    # Sample 3: Another test clip from filesamples
    ["sample3.mp4"]="https://filesamples.com/samples/video/mp4/sample_1280x720_surfing_with_audio.mp4"
)

download_count=0
skip_count=0
fail_count=0

for filename in "${!VIDEOS[@]}"; do
    url="${VIDEOS[$filename]}"
    dest="${SAMPLES_DIR}/${filename}"

    if [ -f "$dest" ]; then
        echo "[SKIP] ${filename} already exists at ${dest}"
        skip_count=$((skip_count + 1))
        continue
    fi

    echo "[DOWNLOAD] ${filename} from ${url}"
    if curl -fsSL --connect-timeout 10 --max-time 60 -o "$dest" "$url" 2>/dev/null; then
        echo "[OK] Downloaded ${filename} ($(du -h "$dest" | cut -f1))"
        download_count=$((download_count + 1))
    else
        echo "[WARN] Failed to download ${filename} from ${url} — skipping"
        rm -f "$dest"
        fail_count=$((fail_count + 1))
    fi
done

echo ""
echo "=== Download summary ==="
echo "  Downloaded: ${download_count}"
echo "  Skipped (existing): ${skip_count}"
echo "  Failed: ${fail_count}"
echo "  Output dir: ${SAMPLES_DIR}"
echo ""

if [ "$download_count" -eq 0 ] && [ "$skip_count" -eq 0 ]; then
    echo "[WARN] No videos available. The simulator will run without video input."
    echo "       Place MP4 files in ${SAMPLES_DIR}/ manually if needed."
fi
