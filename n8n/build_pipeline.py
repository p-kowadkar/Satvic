import json
import os
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "workflows")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# These four IDs are specific to one n8n instance -- they won't exist on a
# fresh clone. Create the two Header Auth credentials (Settings ->
# Credentials) and PUT the generated JSON to a new workflow once to get real
# IDs back, then update these. FORM_WEBHOOK_ID can be any UUID you like; it
# just needs to stay stable so the form's URL doesn't change between builds.
SARVAM_CRED = {"id": "zvfdmGZtDzNvAiox", "name": "Header Auth account"}
ELEVEN_CRED = {"id": "wRmIlMYLx46TgojX", "name": "Header Auth account 2"}
MAIN_WF_ID = "wjqdxGJUmlSsCv5N"
PROCESSING_WF_ID = "8P4WWcGgRZ76UzUq"
FORM_WEBHOOK_ID = "922ad204-cd1c-4c6e-b24d-1b22108e3e9f"

# ---------------------------------------------------------------- helpers --

def code(name, js_code, mode=None):
    params = {"jsCode": js_code}
    if mode:
        params["mode"] = mode
    return {"parameters": params, "type": "n8n-nodes-base.code", "typeVersion": 2, "name": name}

def exec_cmd(name, command, execute_once=None, continue_on_fail=False):
    if not command.startswith("="):
        command = "=" + command
    params = {"command": command}
    if execute_once is not None:
        params["executeOnce"] = execute_once
    node = {"parameters": params, "type": "n8n-nodes-base.executeCommand", "typeVersion": 1, "name": name}
    if continue_on_fail:
        node["onError"] = "continueRegularOutput"
    return node

def read_file(name, file_selector):
    return {"parameters": {"fileSelector": file_selector, "options": {}},
            "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1.1, "name": name}

def write_file(name, file_name):
    return {"parameters": {"operation": "write", "fileName": file_name, "options": {}},
            "type": "n8n-nodes-base.readWriteFile", "typeVersion": 1.1, "name": name}

def _rate_limit_safety(node, max_tries=5, wait_between_tries=4000):
    node["retryOnFail"] = True
    node["maxTries"] = max_tries
    node["waitBetweenTries"] = wait_between_tries
    return node

def http_json(name, url, credential, body_params, method="POST", response_file=False, continue_on_fail=False):
    options = {}
    if response_file:
        options["response"] = {"response": {"responseFormat": "file"}}
    node = {
        "parameters": {
            "method": method, "url": url,
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendBody": True, "contentType": "json", "specifyBody": "keypair",
            "bodyParameters": {"parameters": body_params}, "options": options,
        },
        "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.4, "name": name,
        "credentials": {"httpHeaderAuth": credential},
    }
    node = _rate_limit_safety(node)
    if continue_on_fail:
        node["onError"] = "continueRegularOutput"
    return node

def http_json_raw(name, url, credential, json_body_expr, method="POST", response_file=False, continue_on_fail=False):
    options = {}
    if response_file:
        options["response"] = {"response": {"responseFormat": "file"}}
    node = {
        "parameters": {
            "method": method, "url": url,
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendBody": True, "contentType": "json", "specifyBody": "json",
            "jsonBody": json_body_expr, "options": options,
        },
        "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.4, "name": name,
        "credentials": {"httpHeaderAuth": credential},
    }
    node = _rate_limit_safety(node)
    if continue_on_fail:
        node["onError"] = "continueRegularOutput"
    return node

def http_multipart(name, url, credential, body_params):
    node = {
        "parameters": {
            "method": "POST", "url": url,
            "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
            "sendBody": True, "contentType": "multipart-form-data",
            "bodyParameters": {"parameters": body_params}, "options": {},
        },
        "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.4, "name": name,
        "credentials": {"httpHeaderAuth": credential},
    }
    return _rate_limit_safety(node)

def http_get_plain(name, url):
    # No auth needed -- used for presigned Azure blob URLs. authentication
    # must be explicitly "none": omitting the field entirely caused the node
    # to silently no-op (echo its input back) instead of making the request.
    return {
        "parameters": {"method": "GET", "url": url, "authentication": "none", "options": {}},
        "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.4, "name": name,
    }

def wait_node(name, amount, unit="seconds"):
    params = {"amount": amount}
    if unit != "seconds":
        params["unit"] = unit
    return {"parameters": params, "type": "n8n-nodes-base.wait", "typeVersion": 1.1,
            "name": name, "webhookId": str(uuid.uuid4())}

def loop_over_items(name, batch_size=1):
    params = {}
    if batch_size != 1:
        params["batchSize"] = batch_size
    return {"parameters": params, "type": "n8n-nodes-base.splitInBatches", "typeVersion": 3, "name": name}

def if_node(name, left_expr, right_value):
    return {
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 3},
                "conditions": [{
                    "id": str(uuid.uuid4()), "leftValue": left_expr, "rightValue": right_value,
                    "operator": {"type": "string", "operation": "equals", "name": "filter.operator.equals"},
                }],
                "combinator": "and",
            },
            "options": {},
        },
        "type": "n8n-nodes-base.if", "typeVersion": 2.3, "name": name,
    }

def webhook_node(name, path, response_mode="lastNode"):
    return {"parameters": {"path": path, "responseMode": response_mode, "options": {}},
            "type": "n8n-nodes-base.webhook", "typeVersion": 2.1, "name": name,
            "webhookId": str(uuid.uuid4())}

def respond_to_webhook(name, respond_with="binary"):
    return {"parameters": {"respondWith": respond_with, "options": {}},
            "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.5, "name": name}

def execute_workflow(name, workflow_id, workflow_name, wait_for_completion=True):
    return {
        "parameters": {
            "source": "database",
            "workflowId": {"__rl": True, "value": workflow_id, "mode": "list", "cachedResultName": workflow_name},
            "options": {"waitForSubWorkflow": wait_for_completion},
        },
        "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.3, "name": name,
    }

def execute_workflow_trigger(name):
    return {"parameters": {"inputSource": "passthrough"}, "type": "n8n-nodes-base.executeWorkflowTrigger",
            "typeVersion": 1.1, "name": name}


def finalize(nodes, connections, name, workflow_id=None):
    x, y_base = 0, 0
    for n in nodes:
        n["id"] = str(uuid.uuid4())
        if "position" not in n:
            n["position"] = [x, y_base]
            x += 240
    payload = {"name": name, "nodes": nodes, "connections": connections,
               "settings": {"executionOrder": "v1"}}
    return payload


LANG_MAP_JS = """
const langMap = {
  Kannada: { sarvam: 'kn-IN', eleven: 'kn', subtitle: 'kan' },
  Telugu: { sarvam: 'te-IN', eleven: 'te', subtitle: 'tel' },
  Malayalam: { sarvam: 'ml-IN', eleven: 'ml', subtitle: 'mal' },
  Tamil: { sarvam: 'ta-IN', eleven: 'ta', subtitle: 'tam' },
  Marathi: { sarvam: 'mr-IN', eleven: 'mr', subtitle: 'mar' },
};
""".strip()

# ============================================================ MAIN WORKFLOW

main_nodes = []
main_conn = {}

main_nodes.append({
    "parameters": {
        "formTitle": "Satvic Dubbing Pipeline",
        "formFields": {"values": [
            {"fieldLabel": "Video path"},
            {"fieldLabel": "Source language", "fieldType": "dropdown", "fieldOptions": {"values": [{"option": "Hindi"}]}},
            {"fieldLabel": "Target language", "fieldType": "dropdown", "fieldOptions": {"values": [
                {"option": "Kannada"}, {"option": "Telugu"}, {"option": "Malayalam"},
                {"option": "Tamil"}, {"option": "Marathi"},
            ]}},
            {"fieldLabel": "ElevenLabs voice_id"},
            {"fieldLabel": "Keep original timestamps (optional)", "requiredField": False},
        ]},
        "responseMode": "lastNode", "options": {},
    },
    "type": "n8n-nodes-base.formTrigger", "typeVersion": 2.6,
    "name": "On form submission", "webhookId": FORM_WEBHOOK_ID,
})

main_nodes.append(code("Init Job", f"""
{LANG_MAP_JS}
const item = $input.first().json;
const targetLanguage = item['Target language'];
const codes = langMap[targetLanguage];
if (!codes) {{
  throw new Error(`Unsupported target language: ${{targetLanguage}}`);
}}
const jobId = `job_${{Date.now()}}`;

// "1:26-2:20, 8:45-9:02" -> [{{startMs,endMs}}, ...]. These windows keep the
// original audio (no dub) regardless of what diarization says, if anything
// -- a manual override for exactly the case diarization can't be trusted
// for yet. Accepts mm:ss or h:mm:ss per side; a bare number is seconds.
function parseTimeToMs(t) {{
  const parts = t.trim().split(':').map(Number);
  if (parts.some(isNaN)) return NaN;
  if (parts.length === 3) return ((parts[0] * 60 + parts[1]) * 60 + parts[2]) * 1000;
  if (parts.length === 2) return (parts[0] * 60 + parts[1]) * 1000;
  return parts[0] * 1000;
}}
const rawRanges = (item['Keep original timestamps (optional)'] || '').trim();
const keepOriginalRanges = rawRanges
  ? rawRanges.split(',').map(chunk => {{
      const [s, e] = chunk.split('-');
      if (s == null || e == null) return null;
      const startMs = parseTimeToMs(s);
      const endMs = parseTimeToMs(e);
      return (isNaN(startMs) || isNaN(endMs)) ? null : {{ startMs, endMs }};
    }}).filter(Boolean)
  : [];

return [{{
  json: {{
    jobId,
    videoPath: item['Video path'],
    voiceId: item['ElevenLabs voice_id'],
    sourceLangCode: 'hi-IN',
    targetLanguage,
    targetSarvamCode: codes.sarvam,
    targetElevenCode: codes.eleven,
    targetSubtitleCode: codes.subtitle,
    keepOriginalRanges,
    outputDir: `/satvic/n8n_output/${{jobId}}`,
  }},
}}];
""".strip()))

# Live-confirmed race: n8n does not guarantee a short dead-end side-branch
# (a status writer, in this case) executes promptly relative to the long
# main chain it branched off of -- a 'translate' stage write was observed
# firing (and winning) *after* the pipeline's own 'done' write finished,
# because n8n's scheduler queued it late. Every status writer below now
# reads the existing file first and only overwrites if the new write
# outranks the current one, so out-of-order execution can no longer regress
# a completed/errored job back to an earlier-looking stage. Priority is by
# status first (error always wins, complete beats any in-progress write,
# regardless of which stage name each used -- STT errors write stage:"stt",
# which isn't even one of the normal progress stages) and stage only breaks
# ties within "processing". Two copies below: PRIORITY_FN_SQ for nodes
# wrapped in node -e "..." (JS strings must use single quotes inside), and
# PRIORITY_FN_DQ for nodes wrapped in node -e '...' (JS strings use double
# quotes inside) -- matching whichever convention that node already uses.
PRIORITY_FN_SQ = (
    "function pr(s){if(!s||!s.status)return -1;"
    "if(s.status==='error')return 100;if(s.status==='complete')return 99;"
    "var sp={starting:0,translate:1,tts:2};return sp[s.stage]!=null?sp[s.stage]:0;}"
)
PRIORITY_FN_DQ = (
    "function pr(s){if(!s||!s.status)return -1;"
    "if(s.status===\"error\")return 100;if(s.status===\"complete\")return 99;"
    "var sp={starting:0,translate:1,tts:2};return sp[s.stage]!=null?sp[s.stage]:0;}"
)

main_nodes.append(exec_cmd(
    "Write Initial Status",
    "mkdir -p {{ $json.outputDir }} && node -e \""
    "var fs = require('fs'); "
    "var p = '{{ $json.outputDir }}/status.json'; "
    + PRIORITY_FN_SQ + " "
    "var cur = {}; try { cur = JSON.parse(fs.readFileSync(p, 'utf-8')); } catch(e) {} "
    "var ns = {status:'processing', stage:'starting', job_id:'{{ $json.jobId }}', "
    "target_language:'{{ $json.targetLanguage }}'}; "
    "if (pr(ns) >= pr(cur)) { fs.writeFileSync(p, JSON.stringify(ns)); }\""
))

# Write Initial Status is an Execute Command node -- it replaces json with
# {exitCode, stdout, stderr}, wiping the job context. Restore it before
# dispatching to the sub-workflow.
main_nodes.append(code("Restore Job Context", "return [{ json: $('Init Job').first().json }];"))

main_nodes.append(execute_workflow("Dispatch Processing", PROCESSING_WF_ID, "Satvic Dubbing Processing", wait_for_completion=False))

main_nodes.append(code("Build Dispatch Response", """
const ctx = $('Init Job').first().json;
return [{
  json: {
    job_id: ctx.jobId,
    target_language: ctx.targetLanguage,
    status_check_url: `http://localhost:5680/webhook/satvic-status?job=${ctx.jobId}`,
  },
}];
""".strip()))

POLL_JS = """
async function poll() {
  try {
    const res = await fetch(statusUrl);
    const data = await res.json();
    if (data.status === 'complete') {
      document.getElementById('statusArea').innerHTML =
        '<div style="font-size:48px;line-height:1">&#9989;</div>' +
        '<h1 style="margin:16px 0 8px">Dubbing complete</h1>' +
        '<p style="color:#555;margin:0 0 28px">' + (data.segment_count || 0) +
        ' segment(s) dubbed into ' + data.target_language + '.</p>' +
        '<table style="width:100%;text-align:left;border-collapse:collapse;background:#f7f7f8;border-radius:8px;overflow:hidden">' +
        '<tr><td style="padding:12px 16px;color:#888;font-size:13px">Job ID</td>' +
        '<td style="padding:12px 16px;font-family:monospace;font-size:13px">' + data.job_id + '</td></tr>' +
        '<tr><td style="padding:12px 16px;color:#888;font-size:13px;border-top:1px solid #eaeaea">Saved to</td>' +
        '<td style="padding:12px 16px;font-family:monospace;font-size:12px;word-break:break-all;border-top:1px solid #eaeaea">' +
        data.output_path + '</td></tr></table>' +
        '<div style="margin-top:28px;display:flex;gap:12px;justify-content:center;flex-wrap:wrap">' +
        '<a href="' + data.video_serve_url + '" target="_blank" style="display:inline-block;background:#1a1a1a;color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:600">&#9654; Open video</a>' +
        '<button type="button" onclick="navigator.clipboard.writeText(\\'' + data.host_path + '\\');this.innerText=\\'Copied!\\'" style="background:#eee;color:#1a1a1a;padding:14px 28px;border-radius:8px;border:none;font-weight:600;font-family:inherit;font-size:14px;cursor:pointer">Copy video path</button>' +
        '<a href="/form/922ad204-cd1c-4c6e-b24d-1b22108e3e9f" style="display:inline-block;background:#f4714c;color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:600">Dub another video</a>' +
        '</div>';
    } else if (data.status === 'failed') {
      document.getElementById('statusArea').innerHTML =
        '<div style="font-size:48px;line-height:1">&#10060;</div>' +
        '<h1 style="margin:16px 0 8px">Dubbing failed</h1>' +
        '<p style="color:#555">' + (data.error || 'Unknown error') + '</p>';
    } else {
      document.getElementById('stageText').innerText = 'Stage: ' + (data.stage || 'processing') + '...';
      setTimeout(poll, 5000);
    }
  } catch (e) {
    setTimeout(poll, 5000);
  }
}
poll();
""".strip()

main_nodes.append({
    "parameters": {
        "operation": "completion", "respondWith": "showText",
        "responseText": (
            "=<div id=\"statusArea\" style=\"font-family:-apple-system,Helvetica,Arial,sans-serif;"
            "max-width:480px;margin:60px auto;text-align:center;color:#1a1a1a\">"
            "<div style=\"font-size:48px;line-height:1\">&#9203;</div>"
            "<h1 style=\"margin:16px 0 8px\">Processing started</h1>"
            "<p style=\"color:#555;margin:0 0 8px\">Job ID: <code>{{ $json.job_id }}</code></p>"
            "<p id=\"stageText\" style=\"color:#888;font-size:13px\">Stage: starting...</p>"
            "<p style=\"color:#aaa;font-size:12px;margin-top:24px\">This page updates automatically -- "
            "no need to refresh.</p>"
            "</div>"
            "<script>const statusUrl = '{{ $json.status_check_url }}';\n" + POLL_JS + "</script>"
        ),
        "options": {},
    },
    "type": "n8n-nodes-base.form", "typeVersion": 2.5,
    "name": "Dispatch Screen", "webhookId": str(uuid.uuid4()),
})

main_conn["On form submission"] = {"main": [[{"node": "Init Job", "type": "main", "index": 0}]]}
main_conn["Init Job"] = {"main": [[{"node": "Write Initial Status", "type": "main", "index": 0}]]}
main_conn["Write Initial Status"] = {"main": [[{"node": "Restore Job Context", "type": "main", "index": 0}]]}
main_conn["Restore Job Context"] = {"main": [[{"node": "Dispatch Processing", "type": "main", "index": 0}]]}
main_conn["Dispatch Processing"] = {"main": [[{"node": "Build Dispatch Response", "type": "main", "index": 0}]]}
main_conn["Build Dispatch Response"] = {"main": [[{"node": "Dispatch Screen", "type": "main", "index": 0}]]}

# --- Serve Video branch (unchanged from v1) ---
main_nodes.append(webhook_node("Serve Video", "satvic-video", "responseNode"))
main_nodes.append(read_file("Read Video File", "=/satvic/n8n_output/{{ $json.query.job }}/final_dubbed.mp4"))
main_nodes.append(respond_to_webhook("Respond With Video", "binary"))
main_conn["Serve Video"] = {"main": [[{"node": "Read Video File", "type": "main", "index": 0}]]}
main_conn["Read Video File"] = {"main": [[{"node": "Respond With Video", "type": "main", "index": 0}]]}

# --- Check Status branch (NEW) ---
main_nodes.append(webhook_node("Check Status", "satvic-status", "lastNode"))
# readWriteFile's binary output is unreliable here -- n8n's filesystem-v2
# binary data manager doesn't resolve .binary.data.data to real file bytes
# inside a Code node (confirmed: it returned identical garbage regardless of
# which file/size was read). node -e + fs.readFileSync is the pattern
# already proven throughout this pipeline, so use it here too. The try/catch
# also covers the natural race where the poller hits this before status.json
# exists yet (right after dispatch).
main_nodes.append(exec_cmd(
    "Read Status File",
    "node -e 'const fs = require(\"fs\"); "
    "try { process.stdout.write(fs.readFileSync(\"/satvic/n8n_output/{{ $json.query.job }}/status.json\", \"utf-8\")); } "
    "catch (e) { process.stdout.write(JSON.stringify({status:\"processing\", stage:\"starting\"})); }'"
))
main_nodes.append(code("Parse Status", "return [{ json: JSON.parse($json.stdout) }];"))
main_conn["Check Status"] = {"main": [[{"node": "Read Status File", "type": "main", "index": 0}]]}
main_conn["Read Status File"] = {"main": [[{"node": "Parse Status", "type": "main", "index": 0}]]}

main_payload = finalize(main_nodes, main_conn, "Satvic Dubbing Pipeline")
# Lay branches out on separate rows so the canvas isn't a big overlapping mess.
mx = 0
for n in main_nodes[:6]:
    n["position"] = [mx, 0]; mx += 240
vx = 0
for n in main_nodes[6:9]:
    n["position"] = [vx, 400]; vx += 240
sx = 0
for n in main_nodes[9:12]:
    n["position"] = [sx, 700]; sx += 240

with open(os.path.join(OUTPUT_DIR, "main_workflow.json"), "w") as f:
    json.dump(main_payload, f, indent=2)
print(f"Main workflow: {len(main_nodes)} nodes")

# ====================================================== PROCESSING WORKFLOW

p_nodes = []
p_conn = {}

def add(node):
    p_nodes.append(node)
    return node["name"]

add(execute_workflow_trigger("When Executed"))

add(exec_cmd(
    "Extract Audio",
    'mkdir -p {{ $json.outputDir }}/tts {{ $json.outputDir }}/aligned {{ $json.outputDir }}/translations && '
    'ffmpeg -y -i "{{ $json.videoPath }}" -vn -ac 1 -ar 16000 "{{ $json.outputDir }}/audio.wav"',
    continue_on_fail=True,
))
# Live-hit: a bad Video path (e.g. a host filesystem path instead of the
# container's /satvic/... mount) fails right here with no error handler,
# and every stage until STT (the first stage that DOES check) has none
# either -- the whole execution just dies silently, leaving status.json
# frozen on "starting" forever with no indication anything went wrong. This
# was the very first real processing step to ever run, so it's the most
# likely place an early failure happens; same pattern as the STT error
# check above.
add(if_node("Extract Audio Succeeded?", "={{ String($json.exitCode) }}", "0"))
add(exec_cmd(
    "Write Extract Audio Error Status",
    "node -e 'const ctx = {{ JSON.stringify($('When Executed').item.json) }}; "
    "const err = {{ JSON.stringify($json.stderr || 'unknown').replace(/'/g, \"'\\\\''\") }}; "
    "const fs = require(\"fs\"); const p = ctx.outputDir + \"/status.json\"; "
    + PRIORITY_FN_DQ + " "
    "let cur = {}; try { cur = JSON.parse(fs.readFileSync(p, \"utf-8\")); } catch(e) {} "
    "const ns = {status:\"error\", stage:\"extract_audio\", job_id: ctx.jobId, target_language: ctx.targetLanguage, "
    "message: \"Audio extraction failed (check the Video path): \" + err}; "
    "if (pr(ns) >= pr(cur)) { fs.writeFileSync(p, JSON.stringify(ns)); }'"
))

# --- Sarvam Batch STT: init -> upload url -> blob PUT + start -> poll -> download -> fetch ---
# with_diarization: pinning num_speakers=2 was believed to fix Sarvam's
# server-side "KeyError: 'timestamps'" crash on longer audio (one clean
# direct-API test after the earlier num_speakers=null failures), but that
# didn't hold up -- 3/3 real attempts through the full pipeline on the
# 18-minute video failed with the identical error even with num_speakers
# pinned. Rolled back to diarization off (temporary, not a verdict on
# whether it's fixable) to get a working full-length run now. Build
# Segments' fallback to plain `timestamps` already handles this gracefully
# -- with no diarized_transcript, everyone is speaker '0', so keepOriginal
# is false for every segment (equivalent to "dub everything"), no other
# code path changes needed. Re-enable by flipping this back to true once
# the crash is actually understood rather than guessed at.
add(http_json_raw(
    "Init STT Job", "https://api.sarvam.ai/speech-to-text/job/v1", SARVAM_CRED,
    "={{ { job_parameters: { language_code: $json.sourceLangCode, model: 'saaras:v3', "
    "mode: 'transcribe', with_timestamps: true, with_diarization: false } } }}",
))

add(http_json_raw(
    "Get Upload URL", "https://api.sarvam.ai/speech-to-text/job/v1/upload-files", SARVAM_CRED,
    "={{ { job_id: $json.job_id, files: ['audio.wav'] } }}",
))

# This n8n image has no curl or apk (see docker-compose.yml comments) --
# confirmed via `docker exec ... which curl` that curl is genuinely absent.
# wget exists but Node 24 (which n8n itself runs on) has native fetch(), so
# this uses node -e for both the blob PUT and the start POST, consistent
# with the node -e pattern already used for status.json writes. Outer
# wrapper is single-quoted deliberately -- see Write Final Status for why.
# SARVAM_API_KEY comes from the container's own process environment (set via
# docker-compose's env_file), not an n8n expression, so no credential wiring
# is needed for this step.
add(exec_cmd(
    "Upload and Start STT Job",
    "node -e 'const fs = require(\"fs\"); "
    "const buf = fs.readFileSync(\"{{ $('When Executed').item.json.outputDir }}/audio.wav\"); "
    "fetch(\"{{ $json.upload_urls['audio.wav'].file_url }}\", "
    "{ method: \"PUT\", headers: {\"x-ms-blob-type\":\"BlockBlob\"}, body: buf })"
    ".then(function(r){ console.log(\"upload:\" + r.status); "
    "return fetch(\"https://api.sarvam.ai/speech-to-text/job/v1/{{ $json.job_id }}/start\", "
    "{ method: \"POST\", headers: {\"api-subscription-key\": process.env.SARVAM_API_KEY, "
    "\"Content-Type\":\"application/json\"}, body: \"{}\" }); })"
    ".then(function(r){ return r.text(); })"
    ".then(function(t){ console.log(t); })"
    ".catch(function(e){ console.error(e); process.exit(1); });'"
))

add(wait_node("Wait STT Poll", 8))

add(http_json(
    "Check STT Status",
    "=https://api.sarvam.ai/speech-to-text/job/v1/{{ $('Init STT Job').item.json.job_id }}/status",
    SARVAM_CRED, [], method="GET",
))

add(if_node("STT Done?", "={{ $json.job_state }}", "Completed"))

# job_state can be "Completed" at the JOB level while the single file inside
# it failed server-side (confirmed live: Sarvam's batch STT backend threw a
# KeyError on 'timestamps' processing an 18-minute file, job_state still
# went to "Completed" with failed_files_count:1 -- a transient error, a
# same-audio same-params retry succeeded seconds later). Without this check,
# "Get Transcript URL" 400s confusingly on a nonexistent output file instead
# of surfacing the real Sarvam-side failure.
add(if_node("STT File Succeeded?", "={{ $json.job_details[0].state }}", "Success"))

add(exec_cmd(
    "Write STT Error Status",
    "node -e 'const ctx = {{ JSON.stringify($(\"When Executed\").item.json) }}; "
    "const err = {{ JSON.stringify($json.job_details[0].error_message || $json.error_message || \"unknown\").replace(/'/g, \"'\\\\''\") }}; "
    "const fs = require(\"fs\"); const p = ctx.outputDir + \"/status.json\"; "
    + PRIORITY_FN_DQ + " "
    "let cur = {}; try { cur = JSON.parse(fs.readFileSync(p, \"utf-8\")); } catch(e) {} "
    "const ns = {status:\"error\", stage:\"stt\", job_id: ctx.jobId, target_language: ctx.targetLanguage, "
    "message: \"Sarvam STT failed: \" + err}; "
    "if (pr(ns) >= pr(cur)) { fs.writeFileSync(p, JSON.stringify(ns)); }'"
))

add(http_json_raw(
    "Get Transcript URL", "https://api.sarvam.ai/speech-to-text/job/v1/download-files", SARVAM_CRED,
    "={{ { job_id: $('Init STT Job').item.json.job_id, "
    "files: [$json.job_details[0].outputs[0].file_name] } }}",
))

# A plain unauthenticated HTTP Request GET node silently no-op'd here
# (echoed its input back, never actually fired the request) across three
# separate fix attempts (Object.values expression, moving extraction to a
# Code node, explicit authentication:"none") -- root cause unclear, but the
# node -e + fetch() pattern already proven for the Azure blob PUT works
# reliably, so using that instead rather than continuing to guess.
add(exec_cmd(
    "Fetch Transcript",
    "node -e 'const fs = require(\"fs\"); "
    "const resp = {{ JSON.stringify($json) }}; "
    "const key = Object.keys(resp.download_urls)[0]; "
    "const url = resp.download_urls[key].file_url; "
    "fetch(url).then(function(r){ return r.text(); })"
    ".then(function(t){ "
    "fs.writeFileSync(\"{{ $('When Executed').item.json.outputDir }}/transcript.json\", t); "
    "console.log(t); })"
    ".catch(function(e){ console.error(e); process.exit(1); });'"
))

add(code("Parse Transcript", """
return [{ json: JSON.parse($json.stdout) }];
""".strip()))

add(code("Build Segments", """
const initJob = $('When Executed').first().json;
const resp = $input.first().json;
const dt = resp.diarized_transcript;
const ts = resp.timestamps;
let entries;
if (dt && dt.entries && dt.entries.length) {
  entries = dt.entries;
} else if (ts && ts.words && ts.words.length) {
  entries = ts.words.map((text, i) => ({
    transcript: text,
    start_time_seconds: ts.start_time_seconds[i],
    end_time_seconds: ts.end_time_seconds[i],
    speaker_id: '0',
  }));
} else {
  entries = [{ transcript: resp.transcript, start_time_seconds: 0, end_time_seconds: 30, speaker_id: '0' }];
}

// Majority speaker by total talk time = the narrator = who we dub. Everyone
// else keeps their original audio -- the timeline assembly step (Build
// Timeline Audio) plays the full original track underneath by default and
// only ducks/overlays it where a dubbed segment exists, so a non-narrator
// segment needs no further processing at all, just to be excluded below.
const talkTime = {};
for (const e of entries) {
  const sid = e.speaker_id != null ? String(e.speaker_id) : '0';
  const dur = (e.end_time_seconds || 0) - (e.start_time_seconds || 0);
  talkTime[sid] = (talkTime[sid] || 0) + dur;
}
const narratorId = Object.keys(talkTime).sort((a, b) => talkTime[b] - talkTime[a])[0];

// Manual "keep original" time windows are handled differently from
// diarization now. Diarization exclusion (below) is genuinely segment-level
// -- a non-narrator speaker owns the whole segment, so excluding it whole
// is correct. Manual ranges are the opposite: the user picked an exact time
// window, not a sentence boundary, and any segment that merely touches it
// got swept in wholesale before (confirmed live -- a 9s requested window
// pulled in ~54s across 4 segments). So a manual range no longer excludes a
// segment from translation/TTS at all -- every segment still gets dubbed --
// instead it's enforced at the audio-mix level in Build Timeline Audio,
// which mutes whatever dub clip is playing during the exact window and
// forces the original back to full volume there, even mid-sentence.
// overlappingRange also drives the subtitle timing below: clamped to the
// actual muted window, not the whole segment, since during the *dubbed*
// portion of that same segment the audio already carries the translation.
const keepOriginalRanges = initJob.keepOriginalRanges || [];
function findOverlappingRange(startMs, endMs) {
  return keepOriginalRanges.find(r => startMs < r.endMs && endMs > r.startMs);
}

let segIndex = 0;
const segments = [];
for (const entry of entries) {
  const text = (entry.transcript || '').trim();
  if (!text) continue;
  const speakerId = entry.speaker_id != null ? String(entry.speaker_id) : '0';
  const startMs = Math.round((entry.start_time_seconds || 0) * 1000);
  const endMs = Math.round((entry.end_time_seconds != null ? entry.end_time_seconds : 30) * 1000);
  const overlappingRange = findOverlappingRange(startMs, endMs);
  segments.push({
    json: {
      ...initJob,
      segmentIndex: segIndex++,
      sourceText: text,
      startMs, endMs,
      speakerId,
      // Editable by hand in segments.json before a resend if this gets a
      // specific segment wrong. Diarization-only now -- a true exclusion,
      // this segment never gets dubbed at all.
      keepOriginal: speakerId !== narratorId,
      // Does NOT gate TTS -- see overlappingRange comment above. Only used
      // to decide whether this (fully-dubbed) segment also needs a
      // subtitle entry for its muted portion.
      overlapsManualRange: !!overlappingRange,
      subtitleStartMs: overlappingRange ? Math.max(startMs, overlappingRange.startMs) : startMs,
      subtitleEndMs: overlappingRange ? Math.min(endMs, overlappingRange.endMs) : endMs,
    },
  });
}
return segments;
""".strip()))

# All segments (both speakers, and both keepOriginal states) go through
# translation -- keepOriginal segments still need translated text for
# subtitles, they just skip TTS later (see "Route By Keep Original", right
# before TTS Loop). Only TTS is the expensive step worth filtering out early.
add(code("Write Segments Checkpoint", """
const items = $input.all();
const content = JSON.stringify(items.map(i => i.json), null, 2);
return [{
  json: { outputDir: items[0].json.outputDir },
  binary: { data: { data: Buffer.from(content).toString('base64'), mimeType: 'application/json', fileName: 'segments.json' } },
}];
""".strip()))

add(write_file("Save Segments File", "={{ $json.outputDir }}/segments.json"))

add(exec_cmd(
    "Status: Translating",
    'node -e "var fs = require(\'fs\'); var p = \'{{ $(\'When Executed\').item.json.outputDir }}/status.json\'; '
    + PRIORITY_FN_SQ +
    ' var cur = {}; try { cur = JSON.parse(fs.readFileSync(p, \'utf-8\')); } catch(e) {} '
    'var ns = {status:\'processing\', stage:\'translate\', job_id:\'{{ $(\'When Executed\').item.json.jobId }}\', '
    'target_language:\'{{ $(\'When Executed\').item.json.targetLanguage }}\'}; '
    'if (pr(ns) >= pr(cur)) { fs.writeFileSync(p, JSON.stringify(ns)); }"'
))

# --- Translate loop: Loop Over Items(1) -> Wait -> Sarvam Translate -> back ---
add(loop_over_items("Translate Loop", batch_size=1))
add(wait_node("Wait Translate", 0.4))
add(http_json(
    "Sarvam Translate", "https://api.sarvam.ai/translate", SARVAM_CRED,
    [
        {"name": "input", "value": "={{ $json.sourceText }}"},
        {"name": "source_language_code", "value": "={{ $json.sourceLangCode }}"},
        {"name": "target_language_code", "value": "={{ $json.targetSarvamCode }}"},
        {"name": "model", "value": "mayura:v1"},
        # User feedback: default formal output read as "too pure" -- this
        # trades a little formality for natural, conversational phrasing.
        {"name": "mode", "value": "modern-colloquial"},
    ],
))
add(code("Merge Translation", """
const original = $('Translate Loop').item.json;
return { json: { ...original, translatedText: ($json.translated_text || '').trim() } };
""".strip(), mode="runOnceForEachItem"))

# Each Sarvam Translate call is paid work. Without this, a mid-run failure
# (rate limit, credits, transient 5xx) loses every already-translated
# segment along with the failed one, since Translate Loop only accumulates
# in memory until the whole batch finishes -- exactly what happened when the
# account ran out of credits at segment 34/76. Appending to disk as each one
# lands means a future failure only costs whatever was still in flight.
# JSON.stringify() only escapes double quotes, not single quotes -- but this
# gets embedded inside a single-quoted shell wrapper. Real translated text
# routinely contains apostrophes (code-switched English inside Kannada/etc,
# e.g. "world's"), which breaks out of the shell quoting and crashes the
# node with "unterminated quoted string" (confirmed live). The .replace
# applies the standard sh single-quote escape (' -> '\'') before embedding.
# execute_once=False -- currently harmless since Translate Loop's batch
# size is 1, but relying on that coincidence is what caused the same class
# of bug on Checkpoint TTS Segment (batch size 3). Setting it explicitly so
# this doesn't silently break if the batch size ever changes.
add(exec_cmd(
    "Checkpoint Translation",
    "node -e 'const fs = require(\"fs\"); "
    "const seg = {{ JSON.stringify($json).replace(/'/g, \"'\\\\''\") }}; "
    "fs.appendFileSync(seg.outputDir + \"/translations.jsonl\", JSON.stringify(seg) + \"\\n\");'",
    execute_once=False,
))

add(code("Add TTS Context", """
const items = $input.all();
const texts = items.map(i => i.json.translatedText || '');
return items.map((item, i) => ({
  json: {
    ...item.json,
    previousText: i > 0 ? texts[i - 1] : '',
    nextText: i < texts.length - 1 ? texts[i + 1] : '',
  },
}));
""".strip()))

add(exec_cmd(
    "Status: TTS",
    'node -e "var fs = require(\'fs\'); var p = \'{{ $(\'When Executed\').item.json.outputDir }}/status.json\'; '
    + PRIORITY_FN_SQ +
    ' var cur = {}; try { cur = JSON.parse(fs.readFileSync(p, \'utf-8\')); } catch(e) {} '
    'var ns = {status:\'processing\', stage:\'tts\', job_id:\'{{ $(\'When Executed\').item.json.jobId }}\', '
    'target_language:\'{{ $(\'When Executed\').item.json.targetLanguage }}\'}; '
    'if (pr(ns) >= pr(cur)) { fs.writeFileSync(p, JSON.stringify(ns)); }"'
))

# keepOriginal segments still went through translation (for subtitles) but
# don't need TTS -- split them off *before* TTS Loop, not inside its cycle.
# An earlier version routed the split inside the loop (a per-item branch
# that either called ElevenLabs or just did a fast disk write, both looping
# back to TTS Loop) and that broke splitInBatches' "done" detection: the
# fast keep-original path would loop back and get counted as done while
# slower in-flight ElevenLabs calls from the same batch hadn't returned yet
# -- confirmed live via runData timestamps, "Build Timeline Audio" fired
# twice, the second time picking up segments the first missed. Filtering
# before the loop keeps every item TTS Loop ever sees on the same uniform,
# already-proven-correct path.
add(if_node("Route By Keep Original", "={{ String($json.keepOriginal) }}", "false"))
# execute_once=False -- same reasoning as every other per-item Execute
# Command node in this pipeline: the default only processes the first item
# of a multi-item execution, not all of them.
add(exec_cmd(
    "Checkpoint Subtitle Segment",
    "node -e 'const fs = require(\"fs\"); "
    "const seg = {{ JSON.stringify($json).replace(/'/g, \"'\\\\''\") }}; "
    "fs.appendFileSync(seg.outputDir + \"/subtitles_checkpoint.jsonl\", JSON.stringify(seg) + \"\\n\");'",
    execute_once=False,
))

# A segment that IS getting dubbed (the true branch above) can still touch a
# manual keep-original range -- it just gets muted for that portion instead
# of excluded entirely (see Build Timeline Audio). It still needs a
# subtitle for that muted stretch, so it *also* branches here in parallel
# with going to TTS Loop, not instead of it.
add(if_node("Overlaps Manual Range?", "={{ String($json.overlapsManualRange) }}", "true"))

# --- TTS loop: Loop Over Items(3) -> Wait -> ElevenLabs TTS (continue-on-fail) -> skip failures -> write/align -> back ---
add(loop_over_items("TTS Loop", batch_size=3))
add(wait_node("Wait TTS", 1.5))
# previous_text/next_text were tried and dropped earlier this session --
# live-confirmed (twice, including a re-test just before this rebuild) that
# eleven_v3 rejects them outright: "Providing previous_text or next_text is
# not yet supported with the 'eleven_v3' model." voice_settings + a fixed
# seed are the two consistency levers that actually work on this model
# (live-tested, HTTP 200) -- switched to http_json_raw since voice_settings
# is a nested object, not expressible in the keypair body format http_json
# uses elsewhere.
add(http_json_raw(
    "ElevenLabs TTS",
    "=https://api.elevenlabs.io/v1/text-to-speech/{{ $json.voiceId }}",
    ELEVEN_CRED,
    "={{ { text: $json.translatedText, model_id: 'eleven_v3', language_code: $json.targetElevenCode, "
    "seed: 42, voice_settings: { stability: 0.7, similarity_boost: 0.8, style: 0.3, use_speaker_boost: true } } }}",
    response_file=True, continue_on_fail=True,
))
add(if_node("TTS Succeeded?", "={{ $json.error ? 'yes-error' : 'no-error' }}", "no-error"))
add(write_file(
    "Write TTS File",
    "={{ $('ElevenLabs TTS').item.json.outputDir }}/tts/seg_"
    "{{ String($('ElevenLabs TTS').item.json.segmentIndex).padStart(4,'0') }}.mp3",
))
add(exec_cmd(
    "Get Clip Duration",
    'ffprobe -v error -show_entries format=duration -of csv=p=0 '
    '"{{ $(\'ElevenLabs TTS\').item.json.outputDir }}/tts/seg_'
    '{{ String($(\'ElevenLabs TTS\').item.json.segmentIndex).padStart(4,\'0\') }}.mp3"',
    execute_once=False,
))
add(code("Compute Atempo Filter", """
const seg = $('ElevenLabs TTS').item.json;
const actualSeconds = parseFloat(($json.stdout || '0').trim()) || 0.1;
const targetSeconds = Math.max((seg.endMs - seg.startMs) / 1000, 0.1);
let ratio = actualSeconds / targetSeconds;
// Only the lower bound is capped -- that's what the original drunk-slow-
// motion complaint was actually about (one real segment hit 0.446x,
// audibly half-speed, to force-fit a short synthesis into a long window).
// An upper cap was added symmetrically alongside it without being
// validated against anything, and it caused a *worse* bug: a clip capped
// at 1.25x when it needed 1.31x to fit still ran 0.86s past its window,
// overlapping into the next segment's dub -- two voices audible at once
// (confirmed live at 1:52-1:53 on a full-video run). Speeding up is far
// more tolerable to listeners than slowing down, and avoiding an audible
// overlap matters more than a mildly faster voice, so the upper side
// force-fits exactly like it did before any capping existed.
ratio = Math.max(0.9, ratio);
const filters = [];
while (ratio > 2.0) { filters.push('atempo=2.0'); ratio /= 2.0; }
while (ratio < 0.5) { filters.push('atempo=0.5'); ratio /= 0.5; }
filters.push(`atempo=${ratio.toFixed(3)}`);
// The timeline assembly step needs to know how long this clip actually
// ends up being (post-atempo) to compute the correct ducking window --
// it's no longer guaranteed to equal endMs - startMs.
const alignedDurationMs = Math.round((actualSeconds / ratio) * 1000);
return { json: { ...seg, atempoFilter: filters.join(','), alignedDurationMs } };
""".strip(), mode="runOnceForEachItem"))

# Same reasoning as Checkpoint Translation -- ElevenLabs TTS is the
# expensive call in this pipeline, and a mid-run failure after this point
# should not throw away audio that's already been paid for and synthesized.
# Same apostrophe-in-shell-quoting fix as Checkpoint Translation too.
# execute_once=False is required, not optional: TTS Loop batches 3 items per
# iteration, and Execute Command's default (unlike every other node type)
# runs ONCE per node execution using only the first item, not once per item
# -- confirmed live: without this, 26 batches produced only 26 checkpoint
# lines instead of 76, silently dropping 2 of every 3 segments. Apply Atempo
# and Get Clip Duration already set this explicitly; this one was missed.
add(exec_cmd(
    "Checkpoint TTS Segment",
    "node -e 'const fs = require(\"fs\"); "
    "const seg = {{ JSON.stringify($json).replace(/'/g, \"'\\\\''\") }}; "
    "fs.appendFileSync(seg.outputDir + \"/tts_checkpoint.jsonl\", JSON.stringify(seg) + \"\\n\");'",
    execute_once=False,
))

add(exec_cmd(
    "Apply Atempo",
    'ffmpeg -y -i "{{ $json.outputDir }}/tts/seg_{{ String($json.segmentIndex).padStart(4,\'0\') }}.mp3" '
    '-filter:a "{{ $json.atempoFilter }}" '
    '"{{ $json.outputDir }}/aligned/seg_{{ String($json.segmentIndex).padStart(4,\'0\') }}_aligned.mp3"',
    execute_once=False,
))

# Replaces the old concat-demuxer approach (butt-joining clips back to
# back) with a real timeline assembly: the ORIGINAL audio plays as a base
# layer for the whole video, fully muted under each dubbed segment's window
# (was 0.12 -- an arbitrary, never-actually-validated "quiet backdrop"
# choice that turned out to just sound like distracting background bleed
# under every dubbed line) and back to full volume everywhere else, with
# each dubbed clip
# mixed in (adelay'd to its real startMs) on top. This fixes three separate
# problems the concat approach had: (1) non-narrator speech (team members
# on camera) now keeps its real audio instead of getting silently dropped,
# since only dubbed segments are in tts_checkpoint.jsonl to begin with; (2)
# duration=first on amix (first = the full-length base track) means the
# output is exactly as long as the source audio, so no more `-shortest`
# truncating a real outro tail the old pipeline was cutting off; (3) reading
# the checkpoint file rather than $('Compute Atempo Filter').all() sidesteps
# the same cross-loop truncation bug documented on the old Build Concat File
# node. execFileSync with a real argv array (not a shell string) avoids
# having to hand-escape N dynamic file paths -- ffmpeg is invoked directly,
# no intermediate shell. normalize=0 on amix is required: amix's default
# normalize=1 divides by the *declared* input count regardless of how many
# are actually non-silent at a given instant, which with ~70+ mostly-silent
# delayed inputs would crush the whole mix to near-silence. \x27 is used
# instead of a literal ' anywhere a quote is needed in generated content, so
# no apostrophe ever appears in the shell-visible node -e source (same class
# of bug as the earlier checkpoint fix).
# Manual keep-original ranges are now enforced here, at the mix, not by
# excluding segments earlier -- every segment gets dubbed regardless, and
# this is what makes a manual range authoritative down to the exact
# millisecond instead of "whichever whole sentence happens to touch it."
# Two additions to the filter graph: (1) the base (original) duck
# expression gets a manual-range override checked *last* (outermost, so it
# wins) forcing 1.0 regardless of any dub segment's own window; (2) every
# individual dub clip gets the *same* mute expression applied after its
# adelay, so it goes silent during a manual range even mid-sentence, then
# resumes after. Both expressions operate on the same absolute-time `t` (via
# adelay shifting each clip into its real position), so they line up.
#
# Every transition used to be an instant digital on/off, and that was
# audible in two ways once someone actually listened closely: (a) a hard
# mid-sentence cut right where a manual range starts/ends (live-confirmed --
# a segment's dub was still playing when the range's mute kicked in,
# chopping it off 1.9s early), and (b) segment-to-segment handoffs between
# separate ElevenLabs calls sounding abrupt even after the overlap fix,
# since each call has its own slight voice delivery even with the same
# voice_settings/seed (eleven_v3 has no cross-call stitching -- confirmed,
# see ElevenLabs TTS above). Two fixes, both just short linear ramps instead
# of instant steps: a 150ms crossfade at each manual range's boundary (duck
# ramps toward original, mute ramps toward silence, symmetric so they hand
# off cleanly -- this does mean original audio can start up to 150ms before
# the exact requested boundary, a small, deliberate trade against an
# audible hard cut) and an 80ms afade in/out on every individual dub clip
# (capped to a quarter of a very short clip's own duration so it can never
# fade over the whole thing), which softens every segment-to-segment
# handoff generally, not just the manual-range ones -- doesn't eliminate a
# genuine voice-timbre difference between two API calls, but a smooth
# handoff reads as far less jarring than a hard cut landing on top of one.
add(exec_cmd(
    "Build Timeline Audio",
    "node -e 'const fs = require(\"fs\"); "
    "const cp = require(\"child_process\"); "
    "const dir = \"{{ $('When Executed').item.json.outputDir }}\"; "
    "const keepOriginalRanges = {{ JSON.stringify($('When Executed').item.json.keepOriginalRanges) }}; "
    "const lines = fs.existsSync(dir + \"/tts_checkpoint.jsonl\") "
    "? fs.readFileSync(dir + \"/tts_checkpoint.jsonl\", \"utf-8\").trim().split(\"\\n\").filter(Boolean).map(function(l){ return JSON.parse(l); }) "
    ": []; "
    "lines.sort(function(a,b){ return a.segmentIndex - b.segmentIndex; }); "
    "if (lines.length === 0) { "
    "fs.copyFileSync(dir + \"/audio.wav\", dir + \"/final_audio.mp3\"); "
    "} else { "
    "const F = 0.15; "
    "let duckExpr = \"1\"; "
    "lines.forEach(function(item){ "
    "const s = item.startMs / 1000; const e = (item.startMs + item.alignedDurationMs) / 1000; "
    "duckExpr = \"if(between(t,\" + s + \",\" + e + \"),0,\" + duckExpr + \")\"; }); "
    "let muteExpr = \"1\"; "
    "keepOriginalRanges.forEach(function(r){ "
    "const s = r.startMs / 1000; const e = r.endMs / 1000; "
    "muteExpr = \"if(between(t,\" + s + \",\" + e + \"),0,\" + muteExpr + \")\"; }); "
    "keepOriginalRanges.forEach(function(r){ "
    "const s = r.startMs / 1000; const e = r.endMs / 1000; "
    "duckExpr = \"if(between(t,\" + (s - F) + \",\" + s + \"),(t-(\" + (s - F) + \"))/\" + F + \",\" + "
    "\"if(between(t,\" + s + \",\" + e + \"),1,\" + "
    "\"if(between(t,\" + e + \",\" + (e + F) + \"),1-(t-\" + e + \")/\" + F + \",\" + duckExpr + \")))\"; "
    "muteExpr = \"if(between(t,\" + (s - F) + \",\" + s + \"),1-(t-(\" + (s - F) + \"))/\" + F + \",\" + "
    "\"if(between(t,\" + s + \",\" + e + \"),0,\" + "
    "\"if(between(t,\" + e + \",\" + (e + F) + \"),(t-\" + e + \")/\" + F + \",\" + muteExpr + \")))\"; }); "
    "const args = [\"-y\", \"-i\", dir + \"/audio.wav\"]; "
    "lines.forEach(function(item){ "
    "const idx = String(item.segmentIndex).padStart(4, \"0\"); "
    "args.push(\"-i\", dir + \"/aligned/seg_\" + idx + \"_aligned.mp3\"); }); "
    "const filterParts = [\"[0:a]volume=eval=frame:volume=\\x27\" + duckExpr + \"\\x27[base]\"]; "
    "const mixLabels = [\"[base]\"]; "
    "lines.forEach(function(item, i){ "
    "const label = \"[d\" + i + \"]\"; "
    "const durSec = item.alignedDurationMs / 1000; "
    "const fadeD = Math.min(0.08, durSec / 4); "
    "filterParts.push(\"[\" + (i + 1) + \":a]afade=t=in:st=0:d=\" + fadeD + \",afade=t=out:st=\" + (durSec - fadeD) + \":d=\" + fadeD + \",adelay=\" + item.startMs + \",volume=eval=frame:volume=\\x27\" + muteExpr + \"\\x27\" + label); "
    "mixLabels.push(label); }); "
    "filterParts.push(mixLabels.join(\"\") + \"amix=inputs=\" + mixLabels.length + \":duration=first:dropout_transition=0:normalize=0[out]\"); "
    "fs.writeFileSync(dir + \"/filter_complex.txt\", filterParts.join(\";\")); "
    "args.push(\"-filter_complex_script\", dir + \"/filter_complex.txt\", \"-map\", \"[out]\", dir + \"/final_audio.mp3\"); "
    "cp.execFileSync(\"ffmpeg\", args, { stdio: \"inherit\" }); "
    "} "
    "console.log(JSON.stringify({outputDir: dir, videoPath: \"{{ $('When Executed').item.json.videoPath }}\", jobId: \"{{ $('When Executed').item.json.jobId }}\", targetLanguage: \"{{ $('When Executed').item.json.targetLanguage }}\", segmentCount: lines.length}));'"
))
add(code("Parse Timeline Result", """
return [{ json: JSON.parse($json.stdout) }];
""".strip()))

# keepOriginal segments were translated (for exactly this) but never went
# through TTS. Turns their translated text + real timestamps into a soft
# subtitle track, so a target-language viewer isn't just left with a silent
# gap in understanding during an untranslated multi-speaker window. Soft
# (muxed as its own stream, toggle-able) rather than burned in -- doesn't
# permanently alter the video and works in any player that reads mov_text.
add(exec_cmd(
    "Build Subtitle File",
    "node -e 'const fs = require(\"fs\"); "
    "const dir = \"{{ $('Parse Timeline Result').item.json.outputDir }}\"; "
    "const langCode = \"{{ $('When Executed').item.json.targetSubtitleCode }}\"; "
    "let lines = []; "
    "try { lines = fs.readFileSync(dir + \"/subtitles_checkpoint.jsonl\", \"utf-8\").trim().split(\"\\n\").filter(Boolean).map(function(l){ return JSON.parse(l); }); } catch(e) {} "
    "lines.sort(function(a,b){ return a.segmentIndex - b.segmentIndex; }); "
    "function pad(n,len){ return String(n).padStart(len,\"0\"); } "
    "function fmtTime(ms){ "
    "const h = Math.floor(ms/3600000); const m = Math.floor((ms%3600000)/60000); "
    "const s = Math.floor((ms%60000)/1000); const msRem = ms%1000; "
    "return pad(h,2)+\":\"+pad(m,2)+\":\"+pad(s,2)+\",\"+pad(msRem,3); } "
    "const srt = lines.map(function(l, i){ "
    "const s = l.subtitleStartMs != null ? l.subtitleStartMs : l.startMs; "
    "const e = l.subtitleEndMs != null ? l.subtitleEndMs : l.endMs; "
    "return (i+1)+\"\\n\"+fmtTime(s)+\" --> \"+fmtTime(e)+\"\\n\"+l.translatedText+\"\\n\"; "
    "}).join(\"\\n\"); "
    "fs.writeFileSync(dir + \"/subtitles.srt\", srt); "
    "console.log(JSON.stringify({subtitleCount: lines.length, subtitleLangCode: langCode}));'"
))
add(code("Parse Subtitle Result", """
return [{ json: JSON.parse($json.stdout) }];
""".strip()))
add(if_node("Has Subtitles?", "={{ String($json.subtitleCount > 0) }}", "true"))

# No -shortest here anymore -- final_audio.mp3 is already built to the exact
# duration of the original audio (amix duration=first), so the mux should
# just take that length as-is rather than clip to whichever stream is
# shorter.
add(exec_cmd(
    "Mux Final Video (With Subtitles)",
    'ffmpeg -y -i "{{ $(\'Parse Timeline Result\').item.json.videoPath }}" '
    '-i "{{ $(\'Parse Timeline Result\').item.json.outputDir }}/final_audio.mp3" '
    '-i "{{ $(\'Parse Timeline Result\').item.json.outputDir }}/subtitles.srt" '
    '-map 0:v:0 -map 1:a:0 -map 2:s:0 -c:v copy -c:a aac -c:s mov_text '
    '-metadata:s:s:0 language={{ $(\'Parse Subtitle Result\').item.json.subtitleLangCode }} '
    '"{{ $(\'Parse Timeline Result\').item.json.outputDir }}/final_dubbed.mp4"'
))
add(exec_cmd(
    "Mux Final Video (No Subtitles)",
    'ffmpeg -y -i "{{ $(\'Parse Timeline Result\').item.json.videoPath }}" '
    '-i "{{ $(\'Parse Timeline Result\').item.json.outputDir }}/final_audio.mp3" '
    '-map 0:v:0 -map 1:a:0 -c:v copy -c:a aac '
    '"{{ $(\'Parse Timeline Result\').item.json.outputDir }}/final_dubbed.mp4"'
))
# The outer node -e wrapper uses SINGLE quotes deliberately: the {{ }} n8n
# expression below calls JSON.stringify(), whose output always uses DOUBLE
# quotes -- embedding that inside a double-quoted shell wrapper would break
# out of the string. All JS string literals inside therefore use double
# quotes too, so nothing here collides with the outer single quotes.
add(exec_cmd(
    "Write Final Status",
    "node -e 'const ctx = {{ JSON.stringify($(\"Parse Timeline Result\").item.json) }}; "
    "const fs = require(\"fs\"); const p = ctx.outputDir + \"/status.json\"; "
    + PRIORITY_FN_DQ + " "
    "let cur = {}; try { cur = JSON.parse(fs.readFileSync(p, \"utf-8\")); } catch(e) {} "
    "const ns = {"
    "status:\"complete\", stage:\"done\", job_id: ctx.jobId, target_language: ctx.targetLanguage, "
    "segment_count: ctx.segmentCount, output_path: ctx.outputDir + \"/final_dubbed.mp4\", "
    "host_path: (ctx.outputDir + \"/final_dubbed.mp4\").replace(\"/satvic\", \"/Users/pkowadkar/Projects/Satvic\"), "
    "video_serve_url: \"http://localhost:5680/webhook/satvic-video?job=\" + ctx.jobId}; "
    "if (pr(ns) >= pr(cur)) { fs.writeFileSync(p, JSON.stringify(ns)); }'"
))

# ---- connections ----
p_conn["When Executed"] = {"main": [[{"node": "Extract Audio", "type": "main", "index": 0}]]}
p_conn["Extract Audio"] = {"main": [[{"node": "Extract Audio Succeeded?", "type": "main", "index": 0}]]}
# Extract Audio Succeeded? outputs: [0]=true -> continue to STT, [1]=false -> write clear error and stop
p_conn["Extract Audio Succeeded?"] = {"main": [
    [{"node": "Init STT Job", "type": "main", "index": 0}],
    [{"node": "Write Extract Audio Error Status", "type": "main", "index": 0}],
]}
chain = [
    "Init STT Job", "Get Upload URL",
    "Upload and Start STT Job", "Wait STT Poll", "Check STT Status", "STT Done?",
]
for a, b in zip(chain, chain[1:]):
    p_conn[a] = {"main": [[{"node": b, "type": "main", "index": 0}]]}
# STT Done? outputs: [0]=true -> check file-level success, [1]=false -> loop back to Wait
p_conn["STT Done?"] = {"main": [
    [{"node": "STT File Succeeded?", "type": "main", "index": 0}],
    [{"node": "Wait STT Poll", "type": "main", "index": 0}],
]}
# STT File Succeeded? outputs: [0]=true -> continue to transcript, [1]=false -> write clear error and stop
p_conn["STT File Succeeded?"] = {"main": [
    [{"node": "Get Transcript URL", "type": "main", "index": 0}],
    [{"node": "Write STT Error Status", "type": "main", "index": 0}],
]}

chain2 = ["Get Transcript URL", "Fetch Transcript", "Parse Transcript", "Build Segments"]
for a, b in zip(chain2, chain2[1:]):
    p_conn[a] = {"main": [[{"node": b, "type": "main", "index": 0}]]}
# Write Segments Checkpoint collapses all N segment items into one (to save
# the whole array as a single file) and Status: Translating is an Execute
# Command node that wipes json to {exitCode,stdout,stderr} -- both are
# side-effect dead ends. They must branch OFF from Build Segments rather
# than sit inline before Translate Loop, or the main per-segment item flow
# collapses to 1 item before the segments ever reach translation.
p_conn["Build Segments"] = {"main": [[
    {"node": "Write Segments Checkpoint", "type": "main", "index": 0},
    {"node": "Status: Translating", "type": "main", "index": 0},
    {"node": "Translate Loop", "type": "main", "index": 0},
]]}
p_conn["Write Segments Checkpoint"] = {"main": [[{"node": "Save Segments File", "type": "main", "index": 0}]]}
# Translate Loop outputs: [0]=done -> Add TTS Context, [1]=loop -> Wait Translate
p_conn["Translate Loop"] = {"main": [
    [{"node": "Add TTS Context", "type": "main", "index": 0}],
    [{"node": "Wait Translate", "type": "main", "index": 0}],
]}
p_conn["Wait Translate"] = {"main": [[{"node": "Sarvam Translate", "type": "main", "index": 0}]]}
p_conn["Sarvam Translate"] = {"main": [[{"node": "Merge Translation", "type": "main", "index": 0}]]}
p_conn["Merge Translation"] = {"main": [[
    {"node": "Translate Loop", "type": "main", "index": 0},
    {"node": "Checkpoint Translation", "type": "main", "index": 0},
]]}

# Same bug as Build Segments -> Write Segments Checkpoint: Status: TTS is an
# Execute Command node that wipes json to {exitCode,stdout,stderr}. It must
# branch off Add TTS Context as a side effect, not sit inline before TTS
# Loop, or every item loses voiceId/translatedText/etc before ElevenLabs TTS
# ever sees them (this is exactly what produced the malformed "empty voice
# id" URL and the 404 from ElevenLabs).
p_conn["Add TTS Context"] = {"main": [[
    {"node": "Status: TTS", "type": "main", "index": 0},
    {"node": "Route By Keep Original", "type": "main", "index": 0},
]]}
# Route By Keep Original outputs: [0]=true(dub it) -> TTS Loop AND (in
# parallel) check whether it also needs a subtitle for a muted portion,
# [1]=false(non-narrator, excluded entirely) -> subtitle checkpoint, no loop
# involved at all.
p_conn["Route By Keep Original"] = {"main": [
    [{"node": "TTS Loop", "type": "main", "index": 0}, {"node": "Overlaps Manual Range?", "type": "main", "index": 0}],
    [{"node": "Checkpoint Subtitle Segment", "type": "main", "index": 0}],
]}
# Overlaps Manual Range? outputs: [0]=true -> also checkpoint for subtitle, [1]=false -> nothing further needed
p_conn["Overlaps Manual Range?"] = {"main": [
    [{"node": "Checkpoint Subtitle Segment", "type": "main", "index": 0}],
    [],
]}
# TTS Loop outputs: [0]=done -> Build Timeline Audio, [1]=loop -> Wait TTS. Only
# dub items ever reach this loop now, so every item takes the identical path
# -- the asymmetric-latency race is structurally impossible here.
p_conn["TTS Loop"] = {"main": [
    [{"node": "Build Timeline Audio", "type": "main", "index": 0}],
    [{"node": "Wait TTS", "type": "main", "index": 0}],
]}
p_conn["Wait TTS"] = {"main": [[{"node": "ElevenLabs TTS", "type": "main", "index": 0}]]}
p_conn["ElevenLabs TTS"] = {"main": [[{"node": "TTS Succeeded?", "type": "main", "index": 0}]]}
# TTS Succeeded? outputs: [0]=true(no-error) -> Write TTS File, [1]=false(error) -> straight back to loop (skip segment)
p_conn["TTS Succeeded?"] = {"main": [
    [{"node": "Write TTS File", "type": "main", "index": 0}],
    [{"node": "TTS Loop", "type": "main", "index": 0}],
]}
chain4 = ["Write TTS File", "Get Clip Duration", "Compute Atempo Filter"]
for a, b in zip(chain4, chain4[1:]):
    p_conn[a] = {"main": [[{"node": b, "type": "main", "index": 0}]]}
p_conn["Compute Atempo Filter"] = {"main": [[
    {"node": "Apply Atempo", "type": "main", "index": 0},
    {"node": "Checkpoint TTS Segment", "type": "main", "index": 0},
]]}
p_conn["Apply Atempo"] = {"main": [[{"node": "TTS Loop", "type": "main", "index": 0}]]}

chain5 = ["Build Timeline Audio", "Parse Timeline Result", "Build Subtitle File", "Parse Subtitle Result", "Has Subtitles?"]
for a, b in zip(chain5, chain5[1:]):
    p_conn[a] = {"main": [[{"node": b, "type": "main", "index": 0}]]}
# Has Subtitles? outputs: [0]=true -> mux with the soft subtitle track, [1]=false -> mux without (no subtitles.srt to attach)
p_conn["Has Subtitles?"] = {"main": [
    [{"node": "Mux Final Video (With Subtitles)", "type": "main", "index": 0}],
    [{"node": "Mux Final Video (No Subtitles)", "type": "main", "index": 0}],
]}
p_conn["Mux Final Video (With Subtitles)"] = {"main": [[{"node": "Write Final Status", "type": "main", "index": 0}]]}
p_conn["Mux Final Video (No Subtitles)"] = {"main": [[{"node": "Write Final Status", "type": "main", "index": 0}]]}

p_payload = finalize(p_nodes, p_conn, "Satvic Dubbing Processing")
with open(os.path.join(OUTPUT_DIR, "processing_workflow.json"), "w") as f:
    json.dump(p_payload, f, indent=2)
print(f"Processing workflow: {len(p_nodes)} nodes")
