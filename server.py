# server.py
from flask import Flask, request, jsonify, make_response
import os, requests, json
from typing import Dict, Any

app = Flask(__name__)

# -----------------------------
# Config (env-driven)
# -----------------------------
SORA_API_BASE = os.getenv("SORA_API_BASE", "https://api.openai.com/v1")
SORA_API_KEY  = os.getenv("SORA_API_KEY") or os.getenv("OPENAI_API_KEY")
MODEL_ID      = os.getenv("SORA_MODEL_ID", "sora-2")
ACCESS_TOKEN  = os.getenv("MCP_ACCESS_TOKEN")  # optional bearer for production

HTTP_TIMEOUT  = float(os.getenv("HTTP_TIMEOUT", "60"))  # seconds


# -----------------------------
# Utilities
# -----------------------------
def _ok(data: Any, code: int = 200):
    return make_response(jsonify(data), code)

def _err(msg: str, code: int = 400):
    return make_response(jsonify({"ok": False, "error": msg}), code)

def _tool_list() -> Dict[str, Any]:
    """Return tools list with multiple schema shapes for max compatibility."""
    start_job_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "duration": {"type": "number"},
            "aspect_ratio": {"type": "string"},
            "resolution": {"type": "string"},
            "audio": {"type": "boolean"},
            "negative_prompt": {"type": "string"}
        },
        "required": ["prompt"]
    }
    get_job_schema = {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"]
    }

    return {
        "tools": [
            {
                "name": "start_sora_job",
                "description": "Create a Sora video generation job",
                "type": "function",
                # snake_case (MCP style)
                "input_schema": start_job_schema,
                # camelCase mirror (some clients)
                "inputSchema": start_job_schema,
                # OpenAI-style mirror
                "parameters": start_job_schema
            },
            {
                "name": "get_sora_job",
                "description": "Poll a Sora job and return status + asset URLs",
                "type": "function",
                "input_schema": get_job_schema,
                "inputSchema": get_job_schema,
                "parameters": get_job_schema
            }
        ]
    }


# -----------------------------
# CORS & simple auth/logging
# -----------------------------
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp



@app.before_request
def _log_and_auth():
    auth = request.headers.get("Authorization", "")
    # Short log line for debugging in Render
    print(f"[MCP] {request.method} {request.path} Auth:{auth[:20]}...")
    if ACCESS_TOKEN:
        # Accept "Bearer <token>" OR bare token
        if auth == ACCESS_TOKEN or auth == f"Bearer {ACCESS_TOKEN}":
            return
        # For initial setup you can relax this guard; in prod, enforce:
        return _err("Unauthorized", 401)


# -----------------------------
# Health & discovery
# -----------------------------
@app.get("/healthz")
def health():
    return _ok({"ok": True, "status": "healthy"})

@app.route("/", methods=["GET", "POST", "OPTIONS"])
def root_ok():
    return jsonify({
        "name": "sora-mcp",
        "version": "1.0.0",
        "message": "MCP proxy root. See /tools or /mcp/tools for tool catalog.",
        "schema_url": "/.well-known/mcp.json",   # 👈 tells Builder where schema is
        "endpoints": {
            "tools": "/tools",
            "run": "/tools/call",
            "schema": "/.well-known/mcp.json"
        }
    }), 200

def _schema_payload():
    return {
        "name": "sora-mcp",
        "version": "1.0.0",
        "endpoints": {"tools": "/tools", "run": "/tools/call"},
        "tools": [t["name"] for t in _tool_list()["tools"]]
    }

@app.get("/schema.json")
def schema_json():
    return _ok(_schema_payload())

@app.get("/.well-known/mcp.json")
def schema_well_known():
    return _ok(_schema_payload())


# -----------------------------
# Tool catalog (both paths)
# -----------------------------
@app.get("/mcp/tools")
def list_tools_mcp():
    return _ok(_tool_list())

@app.get("/tools")
def list_tools_alias():
    return list_tools_mcp()


# -----------------------------
# Tool execution (both paths)
# -----------------------------
@app.post("/mcp/run")
def run_tool_mcp():
    return _run_tool_impl()

@app.post("/tools/call")
def run_tool_alias():
    return _run_tool_impl()

def _run_tool_impl():
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return _err("Invalid JSON body", 400)

    name = body.get("name") or body.get("tool")  # accept either key
    args  = body.get("arguments") or body.get("input") or {}

    if not name:
        return _err("Missing 'name' (tool) in body", 400)

    headers = {
        "Authorization": f"Bearer {SORA_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        if name == "start_sora_job":
            payload = {
                "model": MODEL_ID,
                "prompt": args.get("prompt"),
                "duration": args.get("duration", 12),
                "aspect_ratio": args.get("aspect_ratio", "16:9"),
                "resolution": args.get("resolution", "1080p"),
                "audio": args.get("audio", True),
                "negative_prompt": args.get("negative_prompt")
            }
            if not payload["prompt"]:
                return _err("start_sora_job requires 'prompt'", 400)

            r = requests.post(
                f"{SORA_API_BASE}/video/jobs",
                headers=headers, json=payload, timeout=HTTP_TIMEOUT
            )
            return _ok({"ok": True, "result": _safe_json(r)})

        elif name == "get_sora_job":
            job_id = args.get("job_id")
            if not job_id:
                return _err("get_sora_job requires 'job_id'", 400)

            r = requests.get(
                f"{SORA_API_BASE}/video/jobs/{job_id}",
                headers=headers, timeout=HTTP_TIMEOUT
            )
            data = _safe_json(r)
            result = {
                "status": data.get("status"),
                "progress": data.get("progress"),
                "video_url": (data.get("output", {})
                                 .get("assets", [{}])[0]
                                 .get("url") if data.get("output") else None),
                "thumbnail_url": data.get("output", {}).get("thumbnail_url"),
                "raw": data
            }
            return _ok({"ok": True, "result": result})

        else:
            return _err(f"Unknown tool '{name}'", 404)

    except requests.exceptions.Timeout:
        return _err("Upstream timeout", 504)
    except requests.exceptions.RequestException as e:
        return _err(f"Upstream error: {e}", 502)


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {"status_code": resp.status_code, "text": resp.text}


# -----------------------------
# Local dev entrypoint
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
