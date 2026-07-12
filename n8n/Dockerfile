# n8nio/n8n:latest is now a hardened/distroless-style Alpine image with apk
# stripped out (n8n >=2.1.0), so packages can't be apk-installed at build time.
# Pull static, dependency-free ffmpeg/ffprobe binaries instead.
FROM mwader/static-ffmpeg:latest AS ffmpeg

FROM n8nio/n8n:latest

USER root

# ffmpeg for time-alignment (atempo) and muxing, exposed to n8n's Execute Command node
COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

USER node
