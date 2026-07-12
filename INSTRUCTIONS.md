# Instructions

## Prerequisites

- Docker
- A Sarvam AI API key ([sarvam.ai](https://sarvam.ai))
- An ElevenLabs API key + a cloned voice ID (Instant Voice Clone, created in
  the ElevenLabs UI from a clean sample of the narrator's voice)

## 1. Environment

```bash
cd n8n
cp .env.example .env
```

Fill in `.env`:
- `SARVAM_API_KEY`
- `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
- `N8N_BASIC_AUTH_PASSWORD` -- set a real one, not the placeholder
- `N8N_LOCAL_API_KEY` -- leave blank for now, filled in after step 2

## 2. Bring up the container

```bash
docker compose up -d --build
docker exec satvic-n8n ffmpeg -version   # confirm ffmpeg is actually present
```

Open `http://localhost:5680`, log in with the basic auth credentials from
`.env`.

Generate an API key: **Settings -> API -> Create API key**, paste it into
`N8N_LOCAL_API_KEY` in `.env`, then restart the container
(`docker compose up -d`) so it picks up the change.

## 3. Set up credentials

**Settings -> Credentials**, create two **Header Auth** credentials:
- One for Sarvam: header name `api-subscription-key`, value = your Sarvam key
- One for ElevenLabs: header name `xi-api-key`, value = your ElevenLabs key

Note the credential IDs (visible in the URL when editing each credential, or
via `GET /api/v1/credentials`) -- you'll need them in the next step.

## 4. Deploy the workflows

`n8n/build_pipeline.py` generates both workflows as JSON and writes them to
`n8n/workflows/`. It does not deploy them itself -- that's a separate `curl`
step, deliberately, so you can inspect the generated JSON before it goes
anywhere.

First, open `build_pipeline.py` and update the instance-specific constants
near the top (`SARVAM_CRED`, `ELEVEN_CRED` IDs from step 3; `MAIN_WF_ID`,
`PROCESSING_WF_ID` -- see below for how to get real IDs on a first deploy).

**First deploy** (creating new workflows, not updating existing ones):

```bash
python3 build_pipeline.py

API_KEY="<your N8N_LOCAL_API_KEY>"

# Create the Processing workflow first -- Main references it, so it must exist first
curl -s -X POST "http://localhost:5680/api/v1/workflows" \
  -H "X-N8N-API-KEY: $API_KEY" -H "Content-Type: application/json" \
  --data @workflows/processing_workflow.json
# Note the returned "id" -> set PROCESSING_WF_ID in build_pipeline.py to this,
# then re-run `python3 build_pipeline.py` to regenerate main_workflow.json
# with the correct reference.

curl -s -X PUT "http://localhost:5680/api/v1/workflows/{PROCESSING_WF_ID}/activate" \
  -H "X-N8N-API-KEY: $API_KEY"

curl -s -X POST "http://localhost:5680/api/v1/workflows" \
  -H "X-N8N-API-KEY: $API_KEY" -H "Content-Type: application/json" \
  --data @workflows/main_workflow.json
# Note the returned "id" -> set MAIN_WF_ID in build_pipeline.py

curl -s -X PUT "http://localhost:5680/api/v1/workflows/{MAIN_WF_ID}/activate" \
  -H "X-N8N-API-KEY: $API_KEY"
```

**After that**, both IDs are fixed and every subsequent change is just:

```bash
python3 build_pipeline.py
curl -s -X PUT "http://localhost:5680/api/v1/workflows/{PROCESSING_WF_ID}" \
  -H "X-N8N-API-KEY: $API_KEY" -H "Content-Type: application/json" \
  --data @workflows/processing_workflow.json
```

(swap in `{MAIN_WF_ID}` / `main_workflow.json` if you changed the main
workflow instead)

The Processing workflow must exist and be published *before* the Main
workflow is imported/updated, or n8n rejects the Execute Workflow node
reference with "workflow X is not published."

## 5. Run a dubbing job

Open the form (the URL is shown in the n8n UI on the Form Trigger node, or
`http://localhost:5680/form/{FORM_WEBHOOK_ID}`):

- **Video path**: a path under `/satvic/...` (the container mounts the whole
  project directory there) -- e.g. `/satvic/input/full_video/n8n_full_clip.mp4`
- **Source language**: Hindi
- **Target language**: Kannada / Telugu / Malayalam / Tamil / Marathi
- **ElevenLabs voice_id**: from `.env`
- **Keep original timestamps (optional)**: comma-separated `start-end` ranges
  to leave untranslated (original audio + a toggleable subtitle track
  instead of a dub), e.g. `1:26-2:20, 8:45-9:02`. Each side accepts `mm:ss`,
  `h:mm:ss`, or a bare number of seconds. Leave blank to dub the whole video.
  Every segment still gets translated/dubbed either way -- these ranges are
  enforced at the final audio mix, not by skipping segments -- so they don't
  reduce ElevenLabs cost, only what's audible in the output (see
  [ARCHITECTURE.md](ARCHITECTURE.md)).

Automatic diarization-based detection (keep the non-narrator speaker's
original voice without specifying timestamps by hand) exists in the
pipeline but is **off by default** -- Sarvam's batch STT backend has a
confirmed server-side crash on longer audio when diarization is on. Use the
manual field above until that's resolved.

Submitting returns a job ID immediately and auto-polls until done, then shows
Open video / Copy video path / Dub another video.

**Test on a short clip first.** A 50-second test is fast (~1-2 minutes
end-to-end) and cheap. Save one under `input/full_video/` before running
anything longer -- see the cost note in [ARCHITECTURE.md](ARCHITECTURE.md).

## 6. Where output lands

`n8n_output/{job_id}/final_dubbed.mp4`, plus every intermediate file
described in ARCHITECTURE.md's data layout -- transcript, per-segment
translations, per-segment audio, the works.

## Debugging a stuck or failed run

`status.json` only updates at stage transitions, so a mid-loop crash (e.g. an
API error not explicitly handled) can leave it looking "stuck" on the last
stage it wrote, even though the underlying execution already died. Check the
real execution state, not just the status file:

```bash
API_KEY="<your N8N_LOCAL_API_KEY>"

# Executions list doesn't reliably surface RUNNING executions by default --
# filter explicitly if you don't see the one you expect
curl -s "http://localhost:5680/api/v1/executions?workflowId={PROCESSING_WF_ID}&status=running" \
  -H "X-N8N-API-KEY: $API_KEY"

# Full detail on a specific execution, including per-node error and data
curl -s "http://localhost:5680/api/v1/executions/{execution_id}?includeData=true" \
  -H "X-N8N-API-KEY: $API_KEY"
```

If a run fails partway through TTS but `tts_checkpoint.jsonl` shows most
segments already succeeded, don't just resubmit the whole video -- check
whether the failure was in aggregation (an on-disk bug) versus the API calls
themselves (needs a real rerun) before spending more credits.

### Regenerating output without new API calls

If the bug is in mixing/muxing logic rather than transcription, translation,
or TTS, you don't need to rerun the whole pipeline (and pay for it again).
Once a job has completed at least once, `n8n_output/{job_id}/` has
everything the final-assembly stages need already on disk:
`segments.json`, `translations.jsonl`, `tts_checkpoint.jsonl` (which points
at the synthesized clips under `aligned/`), and `subtitles_checkpoint.jsonl`.
Re-running just `Build Timeline Audio` / `Build Subtitle File` / the mux step
against that existing job directory reproduces a fix instantly and for free
-- this is how several mixing bugs (background bleed volume, hard cuts at
manual-range boundaries, atempo overlap) were actually fixed and verified
during development.
