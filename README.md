# Satvic

Local, Docker-based Hindi -> Indian-language video dubbing pipeline, built on n8n.

Takes a Hindi video, transcribes it (Sarvam Saaras v3 batch STT), translates each
segment (Sarvam Mayura v1), clones the narrator's voice and re-synthesizes every
segment in the target language (ElevenLabs v3), time-aligns each clip back onto
the original timeline (ffmpeg atempo), and mixes it all into a finished dubbed
video on a millisecond-precise timeline -- all orchestrated through n8n
workflows, defined as code.

Optionally, you can mark exact time windows to keep in the original language
instead of dubbing (e.g. a multi-speaker section) -- those windows get a
toggleable subtitle track instead, so nothing goes untranslated silently.

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

Core pipeline works end-to-end, validated on multiple full-length videos
(~16-19 minutes, Kannada) plus shorter clips across all 5 target languages.
Real output, not a demo -- every run described here is an actual dubbed video
that was watched and iterated on.

Known open issues:

- **Speaker diarization exists but is off by default.** It's meant to
  auto-detect a multi-speaker section and keep the non-narrator speaker's
  original audio. Sarvam's batch STT backend has a confirmed server-side bug
  that throws on longer audio when diarization is on (`KeyError:
  'timestamps'`) -- pinning `num_speakers` was believed to fix it after one
  clean test, but failed 3/3 times on a real full-length run. Until that's
  actually root-caused, the reliable path is the **manual keep-original
  timestamps** field instead -- you tell it exactly which windows to leave
  untranslated, enforced down to the millisecond at the audio mix, not by
  excluding whole sentences.
- **Per-segment time-stretching (atempo) has a lower bound (0.9x) and no
  upper bound.** The lower bound exists to stop a segment from stretching
  into audible slow-motion to fill a long window; leaving the upper bound
  uncapped avoids two dubbed segments audibly overlapping. The trade-off:
  when a segment's synthesized speech is much *shorter* than its window even
  at 0.9x, the clip finishes early and leaves a brief gap where the original
  (untranslated) audio becomes audible until the next segment starts --
  confirmed on a real run, a handful of times in an 18-minute video, one gap
  as long as 9 seconds. Not yet fixed.
- **ElevenLabs v3 voice consistency drifts slightly between separate API
  calls**, even with a fixed `seed` and `voice_settings` (the model doesn't
  support cross-call stitching). Short crossfades at every segment boundary
  soften this but don't eliminate it.
- **Externally-provided transcripts need independent time verification.**
  Tried feeding a third-party timestamped transcript (Gemini-generated) in
  place of Sarvam's own STT for a video where Sarvam's recognition looked
  incomplete -- found the transcript's timestamps drifted ~55s from the
  actual downloaded file (likely transcribed from a different cut/upload of
  the same video). Cross-checked against Sarvam's own STT before trusting
  anything; ended up using Sarvam's transcript since it turned out to be
  complete for that file. The lesson, not (yet) automated: never trust an
  externally-sourced transcript's timestamps against a specific video file
  without verifying against that file's own audio first.

## Quick start

See [INSTRUCTIONS.md](INSTRUCTIONS.md) for environment setup, bringing up the
container, and submitting your first dubbing job.

## Stack

- **Orchestration**: n8n (self-hosted, Docker), workflows generated from Python
- **STT + translation**: Sarvam AI (Saaras v3 batch STT, Mayura v1 translate)
- **Voice cloning + TTS**: ElevenLabs (Instant Voice Clone, `eleven_v3`)
- **Alignment + mixing + muxing**: ffmpeg (native binary, multi-stage Docker
  build) -- timeline-based audio assembly (ducking, muting, crossfades) plus
  soft `mov_text` subtitle muxing for keep-original windows

## License

AGPL-3.0 -- see [LICENSE](LICENSE).
