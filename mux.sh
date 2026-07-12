#!/bin/bash
# Mux the separated video-only and audio-only streams into one playable file.
# Use this to verify the downloaded video is actually the correct one before
# spending any dubbing credits on it.

set -e
cd "$(dirname "$0")"

ffmpeg -i input/video/videoplayback.mp4 -i input/audio/videoplayback.webm \
  -c:v copy -c:a aac \
  -map 0:v:0 -map 1:a:0 \
  input/full_video/satvic_full.mp4

echo ""
echo "Done -> input/full_video/satvic_full.mp4"
echo "Open it, confirm it's the correct video, and note the real runtime"
echo "before running it through Sarvam / ElevenLabs / Open Dubbing."
