# Architecture

## Two workflows

The pipeline is split into two separate n8n workflows, dispatched from one to
the other so the browser never blocks on the actual dubbing work.

**Main workflow** (`n8n/workflows/main_workflow.json`)
- Serves the Form Trigger (video path, source/target language, ElevenLabs
  voice ID, and an optional **keep original timestamps** field)
- On submit: parses the keep-original field into `{startMs, endMs}` ranges,
  writes an initial `status.json`, fires the Processing workflow in
  fire-and-forget mode (`waitForSubWorkflow: false`), and immediately returns
  a "processing started" page with the job ID
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

Diarization (`with_diarization: true`) is deliberately **off** by default.
It was the trigger for a confirmed Sarvam-side server crash on longer audio
(see "Known failure modes" below), and pinning `num_speakers` -- believed at
one point to fix it -- failed 3 of 3 times on a real full-length run despite
one clean direct-API test. `Build Segments` still contains the full
diarization-aware code path (majority-speaker-by-talk-time = narrator,
everyone else excluded from TTS) for whenever that gets root-caused; it just
falls back cleanly to `timestamps`-only segmentation when
`diarized_transcript` is absent -- everyone becomes speaker `'0'`, nobody
gets excluded. The practical replacement for now is the **manual
keep-original timestamp ranges** field (see below), which doesn't depend on
Sarvam's diarization at all.

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

Checkpoint files get written incrementally as the pipeline runs:

- `segments.json` -- written once, right after STT/segmentation, before any
  paid translation/TTS work starts. The reviewable checkpoint: open it,
  hand-edit a bad transcription or a wrong `keepOriginal` flag, before
  regenerating just that segment's audio.
- `translations.jsonl` -- appended to one line at a time, as each segment
  finishes translation.
- `tts_checkpoint.jsonl` -- appended to one line at a time, as each dubbed
  segment finishes TTS + atempo alignment. Includes `alignedDurationMs`
  (the clip's real post-atempo length, since that's no longer guaranteed to
  equal its natural window) -- this is the file the final mix is actually
  built from.
- `subtitles_checkpoint.jsonl` -- appended for any segment that needs a
  subtitle entry: either fully excluded by diarization, or dubbed but
  partially muted by a manual keep-original range.

Both Sarvam and ElevenLabs are paid, per-call APIs. Without checkpointing, a
mid-run failure (rate limit, exhausted API credits, transient server error)
loses every already-completed segment along with the one that failed, since
the loop nodes only accumulate in memory until the whole batch finishes. This
is not hypothetical -- it happened during development: a Sarvam account ran
out of credits at segment 34 of 76, and without checkpointing that would have
meant re-paying for all 34 on retry.

These checkpoints turned out to be useful for more than just resuming a
failed run: several bugs found *after* a job completed successfully (the
background-bleed volume issue, the hard-cut-at-boundary issue, the atempo
overlap fix) were fixed by regenerating just `Build Timeline Audio` and the
final mux from the existing `tts_checkpoint.jsonl` and `aligned/*.mp3` files
-- zero new Sarvam or ElevenLabs calls, just re-running the local ffmpeg
mixing step with corrected logic.

`status.json` is a third, simpler checkpoint: job status/stage, polled by the
main workflow's status webhook to drive the browser's completion page. See
"n8n execution-model gotchas" below for a real race condition that can
corrupt it if every write isn't made monotonic.

## Timeline-based audio mixing (replaces concat)

The final audio isn't built by butt-joining dubbed clips end to end (that
was the first version, and it silently dropped anything that wasn't a dubbed
segment). Instead, `Build Timeline Audio` constructs a single ffmpeg
`filter_complex` graph:

- The **original audio** (`audio.wav`) plays as a base track for the entire
  video, at a computed per-instant volume: `0` (fully muted) under every
  dubbed segment's real window, `1` (full volume) everywhere else. This was
  `0.12` (a quiet backdrop) at one point -- turned out to just be
  distracting background bleed under every dubbed line once someone actually
  listened for it, not a deliberate design choice worth keeping.
- Each **dubbed clip** is `adelay`'d to its real `startMs` and mixed in on
  top (`amix`, `normalize=0` -- required, since `amix`'s default divides by
  the *declared* input count regardless of how many are actually
  non-silent at a given instant, which with 70+ mostly-silent delayed inputs
  crushes the whole mix toward silence).
- `duration=first` on the `amix` (first = the full-length base track) means
  the output is always exactly as long as the source audio -- no `-shortest`
  truncating a real outro tail, which the old concat pipeline did.
- Every individual dub clip gets a short (~80ms) `afade` in/out, and every
  transition at a manual keep-original range boundary gets a 150ms linear
  volume ramp instead of an instant on/off -- see "Known failure modes"
  below for why (a hard mid-sentence cut and abrupt segment-to-segment
  handoffs were both audible before this).

**Known gap**: the per-segment atempo bound (0.9x floor, no ceiling -- see
below) means a clip can occasionally finish *before* its natural window
ends. Nothing currently re-ducks the original back down for that trailing
gap, so a few seconds of untranslated original audio can become briefly
audible there. Confirmed on a real run (a handful of times in an
18-minute video, one gap as long as 9 seconds). Not yet fixed -- the fix
would extend the same crossfade-to-original mechanism already used for
manual ranges to also cover these unintentional gaps.

## Manual keep-original timestamp ranges

The form's "Keep original timestamps" field takes ranges like
`1:26-2:20, 8:45-9:02` (mm:ss or h:mm:ss per side, comma-separated), parsed
in `Init Job` into `{startMs, endMs}` pairs and passed through as
`keepOriginalRanges` on the job context.

**These do not exclude a segment from translation or TTS.** The first
version tried that -- any segment merely *touching* a requested range got
excluded whole -- and a 9-second requested window ended up pulling in ~54
seconds of real narrator content across 4 neighboring segments, because
Sarvam's sentence-level segmentation almost never aligns to a user's chosen
boundary. Every segment now gets dubbed regardless of whether it overlaps a
manual range; the range is enforced **at the mix**, in `Build Timeline
Audio`:

- The base (original) duck expression gets a manual-range override, checked
  last (outermost) so it always wins: forces the original back to full
  volume for that exact window, regardless of what any dub segment's own
  window says.
- Every dub clip gets the identical mute expression applied after its
  `adelay`, so it goes silent during a manual range even mid-sentence, then
  resumes once the range ends.

Both expressions operate on the same absolute timeline (`t`, via `adelay`
shifting each clip into its real position), so they line up exactly. The
trade-off for using a manual range instead of the old segment-exclusion
approach: since every touching segment still gets dubbed (just partially
muted), it costs a little more ElevenLabs usage than segment-exclusion
would have -- worth it for the precision.

## Soft subtitles

Any segment that's excluded from TTS entirely (diarization-excluded, when
diarization is on) or partially muted by a manual range still has real
translated text sitting in `translations.jsonl` -- that's turned into a
subtitle entry instead of just being thrown away, via
`subtitles_checkpoint.jsonl` -> `Build Subtitle File` -> a generated
`subtitles.srt`, muxed as a **soft** (`mov_text`) track, not burned in.
Soft was a deliberate choice over burning it into the video: doesn't
permanently alter the picture, and works in any player that reads `mov_text`
-- though note most players (QuickTime, VLC, browsers) don't auto-enable a
soft subtitle track by default, the viewer has to turn it on.

For a manually-muted (but otherwise dubbed) segment, the subtitle's time
range is clamped to just the muted portion (`subtitleStartMs`/
`subtitleEndMs`, computed in `Build Segments`), not the segment's whole
natural window -- during the *dubbed* portion of that same segment, the
audio already carries the translation, so showing a redundant subtitle
there would be wrong.

If `subtitles_checkpoint.jsonl` ends up empty (no diarization exclusions, no
manual ranges touched), the pipeline branches to a mux variant with no
subtitle input at all (`Has Subtitles?`) rather than trying to attach an
empty `.srt`.

## Data layout

```
n8n_output/{job_id}/
  status.json                    # {status, stage, job_id, target_language, ...}
  segments.json                  # per-segment: sourceText, startMs, endMs, keepOriginal, ...
  translations.jsonl             # append-only, one line per translated segment
  tts_checkpoint.jsonl           # append-only, one line per TTS+aligned segment (incl. alignedDurationMs)
  subtitles_checkpoint.jsonl     # append-only, one line per segment needing a subtitle entry
  audio.wav                      # extracted 16kHz mono source audio
  transcript.json                # raw Sarvam batch STT output
  tts/seg_NNNN.mp3                # raw ElevenLabs synthesis, per segment
  aligned/seg_NNNN_aligned.mp3    # atempo-stretched clip
  filter_complex.txt              # generated ffmpeg filtergraph for the final mix (regenerated each run)
  final_audio.mp3                  # the fully mixed audio track, exact video length
  subtitles.srt                    # generated from subtitles_checkpoint.jsonl, if non-empty
  final_dubbed.mp4                  # final output: video + mixed audio (+ soft subtitle track if any)
```

Note: there's no `concat_list.txt` / concat-demuxer step anymore -- the final
audio is built by a real timeline mix (see below), not by butt-joining clips
back to back.

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

**A `splitInBatches` loop's "done" detection breaks if items inside it take
asymmetric time to complete.** An earlier version of the TTS stage routed
the keep-original/dub split *inside* the loop body -- a per-item branch that
either called ElevenLabs (slow, real API call) or just did a fast disk
write, both looping back to the same `splitInBatches` node. That broke
"done" detection: the fast keep-original path would loop back and get
counted as done while slower in-flight ElevenLabs calls from the *same
batch* hadn't returned yet, so `Build Timeline Audio` fired twice -- the
second time picking up segments the first one missed entirely (confirmed
live via the execution's runData timestamps: a `Checkpoint TTS Segment` ran
*after* the first `Build Timeline Audio` had already started). Fix: filter
before the loop, not inside it, so every item that ever enters a given
`splitInBatches` cycle takes the identical path. This is a general
principle, not specific to this one case -- any time a loop body has a
conditional branch where one path is dramatically faster than the other,
"done" detection is suspect.

**A short dead-end side-branch is not guaranteed to execute promptly
relative to a long chain it branched off of.** Multiple status-writer nodes
(`Status: Translating`, `Status: TTS`) are single-node side branches with no
further downstream connections -- and one was observed, live, executing
*after* the entire rest of the pipeline had already finished and written the
final "complete" status, silently regressing it back to "processing".
n8n's scheduler does not process ready nodes in an order that respects how
"deep" or "long" the branch they're on is. The fix generalizes past this one
case: don't rely on execution order between independent branches at all.
Every status writer here reads the existing file first and only overwrites
if the new write's priority (error > complete > tts > translate > starting)
is >= the current one -- correct regardless of what order the writes
actually land in. Verified with a deliberate out-of-order write simulation,
not just inferred from the one live incident.

## Known failure modes

**Sarvam batch STT transient server error.** Confirmed live: with
diarization enabled, Sarvam's backend can throw `KeyError: 'timestamps'`
server-side while merging diarization output with word timing on longer
audio -- roughly 2 of 3 real attempts on an 18-minute file with
`num_speakers` left unset. Pinning `num_speakers: 2` looked like a fix after
one clean direct-API test, but failed 3 of 3 times on real full-pipeline
runs against an 18-minute video -- so it isn't actually fixed, that early
test result was misleading. The job-level `job_state` still reports
`"Completed"` even when the individual file failed (`job_details[0].state:
"Internal Server Error"`) -- checking only job-level state and proceeding
straight to fetching the transcript produces a confusing 400 on a file that
was never actually written. The pipeline checks file-level state explicitly
(`STT File Succeeded?`) and writes a clear error status instead of crashing
opaquely, regardless of whether diarization is on. Diarization is off by
default now, which avoids the trigger entirely rather than actually solving
it -- see "Why batch STT" above.

**Extract Audio can fail on a bad Video path with no visible error.** Live
example: a host filesystem path (`/Users/.../input/...`) instead of the
container's `/satvic/...` mount. This is the very first real processing
step, before any of the STT-specific error handling exists -- without an
explicit check here, the whole execution just dies, and `status.json` stays
frozen on `"starting"` forever with zero indication anything went wrong.
`Extract Audio` now runs with `continueOnFail`, and an explicit
`Extract Audio Succeeded?` check writes a clear error status
(`stage: "extract_audio"`) if the exit code is non-zero, same pattern as the
STT check.

**ElevenLabs concurrency / credit limits.** A 429 (too many concurrent
requests) or 402 (no credits) surfaces as a normal HTTP error on the
`ElevenLabs TTS` node. `TTS Succeeded?` routes failures straight back into
the TTS loop, skipping that segment rather than failing the whole run --
combined with `tts_checkpoint.jsonl`, a mid-run credit exhaustion only costs
whatever was in flight, not the segments already paid for.

**Atempo bounds trade one audible artifact for a smaller one, not a clean
fix.** See "Timeline-based audio mixing" above -- capping only the lower
bound (0.9x) removes audible overlaps between adjacent dubbed segments but
can leave a short, currently-unhandled gap of original audio when a segment
finishes early.

**ElevenLabs v3 has no cross-call voice consistency mechanism.**
`previous_text`/`next_text` and request-ID-based stitching are both
unsupported on this model (live-confirmed via a direct 400: "Providing
previous_text or next_text is not yet supported with the 'eleven_v3'
model."). `voice_settings` + a fixed `seed` are the two levers that do work,
plus per-clip crossfades to soften the resulting handoffs -- but a genuine
voice-timbre difference between two separate synthesis calls isn't
eliminated, just made less jarring.

**An externally-sourced transcript's timestamps aren't automatically
trustworthy against a specific video file.** Tried feeding a
Gemini-generated timestamped transcript in place of Sarvam's own STT for a
video where Sarvam's recognition looked incomplete. Cross-checked it against
a direct Sarvam STT run on the actual downloaded file before trusting it,
and found the transcript's timestamps drifted ~55 seconds from the real
audio after a certain point, and referenced ~54 seconds of ending content
that doesn't exist in the actual downloaded file at all -- almost certainly
transcribed from a different upload/cut of the same video. Sarvam's own STT
turned out to be complete for that file, so the external transcript wasn't
needed in the end, but the general lesson stands: verify an external
transcript's timing against the real file's own audio (e.g. via a quick
Sarvam STT pass) before trusting its timestamps for dub placement, since a
drifted timestamp would place translated audio over the wrong video content
-- a worse failure than the "missing transcript content" problem an
external transcript is meant to solve.

## Cost shape

Sarvam (STT + translate) is cheap and fast relative to ElevenLabs -- a full
~19-minute video's STT + translation stages together take a few minutes.
ElevenLabs TTS is both the slow part (`eleven_v3`, the only model covering
Kannada/Telugu/Malayalam/Tamil/Marathi, is noticeably slower than the turbo
models -- roughly 20s/segment observed) and the expensive part (a full
~19-minute video costs on the order of 80k+ of a Creator plan's ~100k
monthly credits). Test on a short clip or an excerpt before spending a full
run's credits on an unvalidated change.

**Manual keep-original ranges do not reduce ElevenLabs cost.** Since
enforcement moved to the audio mix rather than excluding segments (see
above), every segment gets dubbed and paid for regardless of whether a
manual range covers part of it -- the range only controls what's audible in
the final mix. Diarization-based exclusion (when/if that's usable again)
*does* reduce cost, since those segments skip TTS entirely.

**Re-running just the final mix (after a mixing-logic fix) costs nothing.**
`Build Timeline Audio` and the mux step only need `tts_checkpoint.jsonl` +
`aligned/*.mp3`, both already on disk after a completed run -- no Sarvam or
ElevenLabs calls involved. Several fixes during development were validated
and applied this way instead of re-running the whole pipeline.
