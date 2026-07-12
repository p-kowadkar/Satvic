# Satvic Dubbing Pipeline — Local n8n Spec

Local, Docker-based replacement for the Lovable web app. Same core pipeline
(Sarvam STT/translate, ElevenLabs clone/TTS, ffmpeg align/mux), zero hosting,
zero auth, full visibility into every intermediate file.

## Why local instead of the Lovable build

- `ffmpeg.wasm` needs cross-origin isolation (COOP+COEP) to unlock
  `SharedArrayBuffer`. The Lovable preview iframe strips those headers, so
  `ffmpeg.load()` fails silently — the entire "nothing happens after upload"
  bug is a platform constraint, not something fixable from inside the app.
  A native ffmpeg binary in Docker has no such requirement — it's just a binary.
- No Supabase/Postgres/RLS, no Google Drive OAuth, no web auth — this is a
  single-user local tool, not a hosted multi-tenant product.
- Every intermediate file lands on disk under `n8n_output/`, inspectable and
  editable by hand at any point — full control, which was the explicit gap
  with the hosted version.

## What carries over from the Lovable build (these were right)

- **Sarvam Saarika v2.5 for STT, not Whisper** — better Hindi accuracy,
  worth keeping regardless of platform.
- **Segment-based, reviewable pipeline**, not one-shot black box — matches
  the brief's own warning that a smooth-but-wrong dub is worse than none.
- **`previous_text` / `next_text` stitching** on the ElevenLabs TTS call —
  passing neighboring segments as context keeps prosody continuous across
  segment boundaries instead of each clip sounding cut off.
- **≤25s chunking before STT** — Sarvam's realtime endpoint caps input at
  under 30 seconds per call.

## Local data layout (mounted into the container at /satvic)

```
~/Projects/Satvic/
  input/
    video/videoplayback.mp4      (video-only, already downloaded)
    audio/videoplayback.webm     (audio-only, already downloaded)
    full_video/                  (muxed video+audio, what you point the form at)
  n8n_output/
    {job_id}/
      segments.json           # source_text, translated_text, start_ms, end_ms, tts_path, status — per segment
      tts/
        seg_0001.mp3
        seg_0002.mp3
      aligned/
        seg_0001_aligned.mp3
      final_audio.mp3
      final_dubbed.mp4
```

`segments.json` is the reviewable checkpoint — open it, read it, hand-edit a
bad translation before regenerating just that segment's audio.

## UI — n8n Form Trigger (not a custom frontend)

n8n's built-in Form Trigger node serves a real form at a local URL and kicks
off the workflow on submission. Four fields is a Form Trigger, not a React app.

Fields:
- **Video path** (text) — e.g. `/satvic/input/full_video/n8n_full_clip.mp4`
- **Source language** (dropdown, default Hindi)
- **Target language** (dropdown: Kannada / Telugu / Malayalam)
- **ElevenLabs voice_id** (text) — Subah's cloned voice ID

## Pipeline nodes, in order

1. **Form Trigger** — collects the four fields above
2. **Execute Command** — extract 16kHz mono WAV (what Sarvam expects):
   `ffmpeg -i {video} -vn -ac 1 -ar 16000 audio.wav`
3. **Execute Command** — split WAV into ≤25s windows
4. **Loop over chunks → HTTP Request → Sarvam `/speech-to-text`** (Saarika v2.5)
   — transcribe each chunk, write into `segments.json` with real timestamps
5. **Loop over segments → HTTP Request → Sarvam `/translate`** (Mayura v1)
   — fill `translated_text`, target language from the form
6. **HTTP Request → ElevenLabs `/v1/text-to-speech/{voice_id}`** per segment
   — `eleven_multilingual_v2`, target `language_code`, plus `previous_text`/
   `next_text` from adjacent segments
7. **Execute Command (ffmpeg atempo)** per segment — stretch/compress each
   clip to fit its `(end_ms - start_ms)` window
8. **Execute Command (ffmpeg concat)** — stitch all aligned clips into
   `final_audio.mp3`
9. **Execute Command (ffmpeg mux)** — `-map 0:v:0 -map 1:a:0 -c:v copy
   -c:a aac` onto `videoplayback.mp4` → `final_dubbed.mp4`
10. **Respond to Form** — return the output path

## Credentials

Set `SARVAM_API_KEY` and `ELEVENLABS_API_KEY` once in n8n's own Credential
store (Settings → Credentials), sourced from `.env` via docker-compose's
`env_file`. Don't hardcode keys into individual HTTP Request nodes.

## Known fiddly part

Step 7's stretch-ratio math is the one place worth testing standalone before
wiring into the full loop — build and test the atempo command against one
segment manually first.
