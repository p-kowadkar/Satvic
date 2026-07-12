# Architecture

## Two workflows

The pipeline is split into two separate n8n workflows, dispatched from one to
the other so the browser never blocks on the actual dubbing work.

**Main workflow** (`n8n/workflows/main_workflow.json`)
- Serves the Form Trigger (video path, source/target language, ElevenLabs
  voice ID)
- On submit: writes an initial `status.json`, fires the Processing workflow
  in fire-and-forget mode (`waitForSubWorkflow: false`), and immediately
  returns a "processing started" page with the job ID
- That page polls a `Check Status` webhook every few seconds and swaps in a
  completion screen (Open video / Copy video path / Dub another video) once
  `status.json` reports `complete`
- A separate `Serve Video` webhook streams the finished file back to the
  browser as `video/mp4`, so "Open video" works as a direct link instead of
  just a filesystem path

**Processing workflow** (`n8n/workflows/processing_workflow.json`)
- Does the actual work: extract audio, batch STT, per-segment translate,
  per-segment voice-clone TTS, per-segment time-align, concat, mux
- Triggered only via Execute Workflow from the main workflow (an Execute
  Workflow Trigger node with `inputSource: passthrough`), never directly by
  a user

Both are generated from one script, `n8n/build_pipeline.py`, and deployed via
n8n's REST API rather than built by hand in the UI. Re-running the script and
`PUT`-ing the result to `/api/v1/workflows/{id}` is the only way changes are
made -- see [INSTRUCTIONS.md](INSTRUCTIONS.md).

## Why fire-and-forget dispatch (not a synchronous form response)

The naive version -- one workflow, Form Trigger straight through to the final
`Respond to Webhook` -- works fine for a 50-second clip but falls over on
anything longer: the form's HTTP connection has to stay open for the entire
run, and a ~20-minute video means a ~20+ minute open connection with nothing
to show for it until the very end.

Splitting into two workflows and firing the second one without waiting means
the form responds in under a second with a job ID, and the browser polls a
cheap status endpoint instead of holding a connection open.

## Why batch STT instead of chunk-and-loop

The original design chunked audio into <=25s windows (Sarvam's realtime STT
cap) and looped a Sarvam call per chunk. That's fine for a 50-second clip (2-3
chunks) and completely impractical for 20 minutes of audio (48+ chunks, each
needing its own chunking logic, rate limiting, and stitching of overlapping
boundaries).

Sarvam's **batch** Speech-to-Text API handles up to 2 hours of audio in one
job: upload the whole file, poll until done, download one transcript with
real per-segment timestamps already computed server-side. This replaced the
entire chunking subsystem with five nodes (init job -> get upload URL -> PUT
to Azure Blob Storage -> poll status -> fetch transcript).

Diarization (`with_diarization: true`) is deliberately **off**. It was the
trigger for a confirmed Sarvam-side server crash on longer audio (see
"Known failure modes" below) and this pipeline doesn't currently use speaker
labels for anything -- segmentation only needs per-segment text + timing,
which the plain `timestamps` field provides on its own (sentence-level
entries with `start_time_seconds`/`end_time_seconds`).

## Why real rate limiting instead of n8n's "Batching" option

The HTTP Request node's built-in Batching option (batch size + interval) does
not reliably serialize requests -- confirmed against ElevenLabs's Creator-plan
concurrency cap (5 concurrent), which still 429'd with Batching configured.
This is a documented, longstanding n8n issue, not a misconfiguration.

The reliable pattern is an explicit **Loop Over Items -> Wait -> API call ->
back to Loop Over Items** cycle: a real graph cycle using the `splitInBatches`
node, verified (via a disposable test workflow) to correctly aggregate all
processed items on its "done" output rather than just re-emitting the
original input. Both the translate stage and the TTS stage use this pattern,
each with its own batch size and wait interval tuned to the respective API's
limits.

## Why on-disk checkpointing, not just in-memory accumulation

Two checkpoint files get written incrementally as the pipeline runs:

- `segments.json` -- written once, right after STT, before any paid
  translation/TTS work starts. The reviewable checkpoint: open it, hand-edit
  a bad translation, before regenerating just that segment's audio.
- `translations.jsonl` / `tts_checkpoint.jsonl` -- appended to one line at a
  time, as each segment finishes translation / TTS+alignment.

Both Sarvam and ElevenLabs are paid, per-call APIs. Without checkpointing, a
mid-run failure (rate limit, exhausted API credits, transient server error)
loses every already-completed segment along with the one that failed, since
the loop nodes only accumulate in memory until the whole batch finishes. This
is not hypothetical -- it happened during development: a Sarvam account ran
out of credits at segment 34 of 76, and without checkpointing that would have
meant re-paying for all 34 on retry.

`status.json` is a third, simpler checkpoint: job status/stage, polled by the
main workflow's status webhook to drive the browser's completion page.

## Data layout

```
n8n_output/{job_id}/
  status.json              # {status, stage, job_id, target_language, ...}
  segments.json            # per-segment: sourceText, startMs, endMs, ...
  translations.jsonl       # append-only, one line per translated segment
  tts_checkpoint.jsonl      # append-only, one line per TTS+aligned segment
  audio.wav                 # extracted 16kHz mono source audio
  transcript.json           # raw Sarvam batch STT output
  tts/seg_NNNN.mp3           # raw ElevenLabs synthesis, per segment
  aligned/seg_NNNN_aligned.mp3   # atempo-stretched to fit its timeline window
  concat_list.txt            # ffmpeg concat demuxer input
  final_audio.mp3
  final_dubbed.mp4            # final output, muxed onto the original video
```

## n8n execution-model gotchas (hard-won, worth knowing before touching this)

**Execute Command replaces `$json` entirely.** Any Execute Command node
downstream of one, in the same linear chain, sees only
`{exitCode, stdout, stderr}` -- every other field is gone. Where a later node
needs both the shell command's output *and* the original item's context
(job ID, output dir, segment text, etc.), the Execute Command node has to
branch off as a side effect from the node before it, in parallel with the
node that continues the real data flow, not sit inline in that flow. This
bit three separate places during development before the pattern was clear.

**Execute Command's default is "once per node execution," not "once per
item."** Every other node type in n8n processes each input item
independently by default. Execute Command does not -- without
`executeOnce: false` set explicitly, a node execution receiving 3 items
(e.g. a batch-of-3 loop iteration) only processes the first one, silently.
This produced a checkpoint file with 26 lines instead of 76 (one per loop
iteration, not one per segment) before being caught.

**`$('NodeName').all()` across a loop cycle can silently truncate.** A Code
node downstream of a completed `splitInBatches` loop, reading a node's full
history via `.all()`, worked correctly on a 3-segment test and truncated to a
single item on a 76-segment run -- despite the referenced node genuinely
having produced all 76 outputs (confirmed via the execution's raw runData).
The exact internal cause (pairedItem resolution across the cycle, possibly
worsened by that node having two downstream branches) wasn't worth chasing
further; the fix was to stop relying on it and read the on-disk checkpoint
file instead, which is both more robust and consistent with the
checkpointing philosophy above.

**`JSON.stringify()` doesn't escape single quotes -- and that matters when
you're building a shell command.** Every "checkpoint" node builds its command
as `node -e '...'` (single-quoted shell wrapper) with a JSON blob of the
current item spliced in via `{{ JSON.stringify($json) }}`. Real translated
text routinely contains apostrophes (code-switched English inside Kannada/
Telugu/etc, e.g. "world's"), which breaks out of the shell's single-quoting
and crashes the node. Fix: `.replace(/'/g, "'\\''")` -- the standard `sh`
single-quote escape -- applied before splicing the JSON in.

**No `curl`, no `apk` in this image.** The hardened Alpine n8n image ships
neither. `wget` is present but the more reliable pattern used throughout
this pipeline is `node -e` with native `fetch()` (Node 24, bundled with
n8n) -- used for the Azure Blob Storage PUT upload and for fetching the
Sarvam transcript download URL, both of which are one-off HTTP calls where a
plain HTTP Request node either wasn't an option (binary PUT with a custom
header) or, in one case, silently no-op'd for reasons never fully pinned
down.

## Known failure modes

**Sarvam batch STT transient server error.** Confirmed live: with
diarization enabled, Sarvam's backend can throw `KeyError: 'timestamps'`
server-side while merging diarization output with word timing on longer
audio, roughly 2 of 3 real attempts on an 18-minute file. The job-level
`job_state` still reports `"Completed"` even when the individual file failed
(`job_details[0].state: "Internal Server Error"`) -- checking only job-level
state and proceeding straight to fetching the transcript produces a
confusing 400 on a file that was never actually written. The pipeline checks
file-level state explicitly (`STT File Succeeded?`) and writes a clear error
status instead of crashing opaquely. Diarization is off by default now (see
above), which removes the trigger entirely.

**ElevenLabs concurrency / credit limits.** A 429 (too many concurrent
requests) or 402 (no credits) surfaces as a normal HTTP error on the
`ElevenLabs TTS` node. `TTS Succeeded?` routes failures straight back into
the TTS loop, skipping that segment rather than failing the whole run --
combined with `tts_checkpoint.jsonl`, a mid-run credit exhaustion only costs
whatever was in flight, not the segments already paid for.

## Cost shape

Sarvam (STT + translate) is cheap and fast relative to ElevenLabs -- a full
~19-minute video's STT + translation stages together take a few minutes.
ElevenLabs TTS is both the slow part (`eleven_v3`, the only model covering
Kannada/Telugu/Malayalam/Tamil/Marathi, is noticeably slower than the turbo
models -- roughly 20s/segment observed) and the expensive part (a full
~19-minute video costs on the order of 80k+ of a Creator plan's ~100k
monthly credits). Test on a short clip or an excerpt before spending a full
run's credits on an unvalidated change.
