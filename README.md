# Satvic

Local, Docker-based Hindi -> Indian-language video dubbing pipeline, built on n8n.

Takes a Hindi video, transcribes it (Sarvam Saaras v3 batch STT), translates each
segment (Sarvam Mayura v1), clones the narrator's voice and re-synthesizes every
segment in the target language (ElevenLabs v3), time-aligns each clip back onto
the original timeline (ffmpeg atempo), and muxes the result into a finished
dubbed video -- all orchestrated through n8n workflows, defined as code.

Supports Kannada, Telugu, Malayalam, Tamil, and Marathi as target languages, on
videos from under a minute up to ~20 minutes (tested end-to-end on both).

## Why this exists

The first version of this was a browser-based tool (Lovable + `ffmpeg.wasm`).
It never got past "nothing happens after upload" -- `ffmpeg.wasm` needs
`SharedArrayBuffer`, which needs cross-origin isolation headers the hosting
iframe stripped. That's a platform constraint, not a bug you can fix from
inside the app.

Moving to a local Docker container with a native ffmpeg binary sidesteps the
entire problem -- it's just a binary, no browser sandboxing involved. It also
means every intermediate file (transcript, per-segment translation, per-segment
audio, alignment) lands on disk and is inspectable and hand-editable at any
point, which matters for a task where a smooth-but-wrong dub is worse than no
dub at all.

## How it's built

The n8n workflows aren't hand-clicked together in the UI -- they're generated
from a single Python script (`n8n/build_pipeline.py`) that defines every node
and connection, then deployed via n8n's REST API. The workflow is code,
versioned, and rebuildable from scratch. See [ARCHITECTURE.md](ARCHITECTURE.md)
for the full design and the specific n8n execution-model bugs that shaped it.

## Status

Core pipeline works end-to-end, validated on a 50-second clip (all 5 target
languages) and a full ~18.7-minute video (Kannada). Known open issues, being
worked on next:

- No speaker diarization yet -- multi-speaker sections (e.g. someone else
  talking on-camera) currently get dubbed in the narrator's cloned voice
  instead of keeping the original audio.
- Per-segment time-stretching (atempo) can occasionally overcorrect on a
  segment where the synthesized clip runs much longer than its window,
  producing a noticeably slow-motion line.
- ElevenLabs v3 voice consistency drifts slightly across a long run --
  stability/seed tuning is the next thing to try.

## Quick start

See [INSTRUCTIONS.md](INSTRUCTIONS.md) for environment setup, bringing up the
container, and submitting your first dubbing job.

## Stack

- **Orchestration**: n8n (self-hosted, Docker), workflows generated from Python
- **STT + translation**: Sarvam AI (Saaras v3 batch STT, Mayura v1 translate)
- **Voice cloning + TTS**: ElevenLabs (Instant Voice Clone, `eleven_v3`)
- **Alignment + muxing**: ffmpeg (native binary, multi-stage Docker build)

## License

AGPL-3.0 -- see [LICENSE](LICENSE).
