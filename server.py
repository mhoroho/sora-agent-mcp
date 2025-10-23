# server.py
"""
Flask + Gunicorn HTTP MCP server with FastMCP-style tools (no stdio).
- Works on Render (Procfile uses gunicorn).
- Exposes HTTP endpoints the Platform Builder probes.
"""

import os
import json
from typing import Optional, Dict, Any
from uuid import uuid4
from flask import Flask, request, jsonify, make_response
import httpx

# Optional: FastMCP for decorator style (we won't run mcp.run_stdio())
try:
    from mcp.server.fastmcp import FastMCP
    _FASTMCP_AVAILABLE = True
except Exception:
    _FASTMCP_AVAILABLE = False

app = Flask(__name__)

# -----------------------------
# Config (env)
# -----------------------------
SORA_API_BASE = os.getenv("SORA_API_BASE", "https://api.openai.com/v1")
SORA_API_KEY  = os.getenv("SORA_API_KEY") or os.getenv("OPENAI_API_KEY")
SORA_MODEL_ID = os.getenv("SORA_MODEL_ID", "sora-2")
ACCESS_TOKEN  = os.getenv("MCP_ACCESS_TOKEN")  # optional bearer
HTTP_TIMEOUT  = float(os.getenv("HTTP_TIMEOUT", "60"))


# -----------------------------
# Helpers
# -----------------------------
def _ok(data: Any, code: int = 200):
    return make_response(jsonify(data), code)

def _err(msg: str, code: int = 400):
    return _ok({"ok": False, "error": msg}, code)

def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except json.JSONDecodeError:
        return {"status_code": resp.status_code, "text": resp.text}

def _start_job_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "duration": {"type": "number"},
            "aspect_ratio": {"type": "string"},
            "resolution": {"type": "string"},
            "audio": {"type": "boolean"},
            "negative_prompt": {"type": "string"},
        },
        "required": ["prompt"],
    }

def _get_job_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    }

def _tool_list_payload() -> Dict[str, Any]:
    start_schema = _start_job_schema()
    get_schema   = _get_job_schema()
    return {
        "tools": [
            {
                "name": "start_sora_job",
                "description": "Create a Sora video generation job",
                "type": "function",
                "input_schema": start_schema,
                "inputSchema": start_schema,     # camelCase mirror
                "parameters": start_schema,      # OpenAI-style mirror
            },
            {
                "name": "get_sora_job",
                "description": "Poll a Sora job and return status + asset URLs",
                "type": "function",
                "input_schema": get_schema,
                "inputSchema": get_schema,
                "parameters": get_schema,
            },
        ]
    }


# -----------------------------
# (Optional) FastMCP-style tool defs
# -----------------------------
if _FASTMCP_AVAILABLE:
    mcp = FastMCP("Sora MCP")

    @mcp.tool()
    def start_sora_job(
        prompt: str,
        duration: float = 12,
        aspect_ratio: str = "16:9",
        resolution: str = "1080p",
        audio: bool = True,
        negative_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not SORA_API_KEY:
            raise RuntimeError("Missing SORA_API_KEY or OPENAI_API_KEY")

        payload = {
            "model": SORA_MODEL_ID,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "audio": audio,
            "negative_prompt": negative_prompt,
        }
        headers = {
            "Authorization": f"Bearer {SORA_API_KEY}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.post(f"{SORA_API_BASE}/video/jobs", headers=headers, json=payload)
            return _safe_json(r)

    @mcp.tool()
    def get_sora_job(job_id: str) -> Dict[str, Any]:
        if not SORA_API_KEY:
            raise RuntimeError("Missing SORA_API_KEY or OPENAI_API_KEY")
        headers = {"Authorization": f"Bearer {SORA_API_KEY}"}
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.get(f"{SORA_API_BASE}/video/jobs/{job_id}", headers=headers)
            data = _safe_json(r)
        assets = (data.get("output") or {}).get("assets") or []
        video_url = (assets[0] or {}).get("url") if assets else None
        return {
            "status": data.get("status"),
            "progress": data.get("progress"),
            "video_url": video_url,
            "thumbnail_url": (data.get("output") or {}).get("thumbnail_url"),
            "raw": data,
        }
else:
    # Fallback: define same functions directly (no FastMCP installed)
    def start_sora_job(**kwargs) -> Dict[str, Any]:
        prompt = kwargs.get("prompt")
        if not prompt:
            raise RuntimeError("start_sora_job requires 'prompt'")
        duration = kwargs.get("duration", 12)
        aspect_ratio = kwargs.get("aspect_ratio", "16:9")
        resolution = kwargs.get("resolution", "1080p")
        audio = kwargs.get("audio", True)
        negative_prompt = kwargs.get("negative_prompt")

        headers = {
            "Authorization": f"Bearer {SORA_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": SORA_MODEL_ID,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "audio": audio,
            "negative_prompt": negative_prompt,
        }
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.post(f"{SORA_API_BASE}/video/jobs", headers=headers, json=payload)
            return _safe_json(r)

    def get_sora_job(**kwargs) -> Dict[str, Any]:
        job_id = kwargs.get("job_id")
        if not job_id:
            raise RuntimeError("get_sora_job requires 'job_id'")
        headers = {"Authorization": f"Bearer {SORA_API_KEY}"}
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.get(f"{SORA_API_BASE}/video/jobs/{job_id}", headers=headers)
            data = _safe_json(r)
        assets = (data.get("output") or {}).get("assets") or []
        video_url = (assets[0] or {}).get("url") if assets else None
        return {
            "status": data.get("status"),
            "progress": data.get("progress"),
            "video_url": video_url,
            "thumbnail_url": (data.get("output") or {}).get("thumbnail_url"),
            "raw": data,
        }


# -----------------------------
# CORS + Auth + Logging
# -----------------------------
@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

from uuid import uuid4

from flask import request, jsonify, make_response
from uuid import uuid4

@app.route("/", methods=["GET", "POST", "OPTIONS"])
def root_jsonrpc():
    # CORS preflight
    if request.method == "OPTIONS":
        return ("", 204)

    # Human-friendly GET for browsers
    if request.method == "GET":
        return _ok({
            "name": "sora-mcp",
            "version": "1.0.0",
            "message": "MCP over HTTP (JSON-RPC 2.0). POST JSON-RPC to this endpoint.",
            "endpoints": {"tools": "/tools", "run": "/tools/call", "schema": "/.well-known/mcp.json"}
        })

    body = request.get_json(silent=True) or {}
    print("[MCP] / body:", body)

    # Helpers
    def rpc_result(id_, result):
        resp = make_response(jsonify({"jsonrpc": "2.0", "id": id_, "result": result}), 200)
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
        return resp

    def rpc_error(id_, code, message, data=None):
        payload = {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}
        if data is not None:
            payload["error"]["data"] = data
        resp = make_response(jsonify(payload), 200)
        resp.headers["Content-Type"] = "application/json; charset=utf-8"
        return resp

    # Not a JSON-RPC request? Show descriptor
    if body.get("jsonrpc") != "2.0" or "method" not in body:
        return _ok({"name": "sora-mcp", "version": "1.0.0", "note": "POST JSON-RPC 2.0 to use MCP"})

    method = body["method"]
    id_ = body.get("id", str(uuid4()))
    params = body.get("params") or {}

    # 1) initialize
    if method == "initialize":
        proto = params.get("protocolVersion", "2025-06-18")
        return rpc_result(id_, {
            "protocolVersion": proto,
            "serverInfo": {"name": "sora-mcp", "version": "1.0.0"},
            "capabilities": {
                "tools": {}  # advertise tools capability
            }
        })

    # 1.1) notifications/initialized (notification → no id, no response body)
    if method == "notifications/initialized":
        return ("", 204)

    # 2) tools/list  —> MUST return tools with inputSchema
    if method == "tools/list":
        tools = [
            {
                "name": "start_sora_job",
                "description": "Create a Sora video generation job",
                "type": "function",
                "inputSchema": {  # 👈 camelCase, JSON Schema for args
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
            },
            {
                "name": "get_sora_job",
                "description": "Poll a Sora job and return status + asset URLs",
                "type": "function",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"}
                    },
                    "required": ["job_id"]
                }
            }
        ]
        return rpc_result(id_, {"tools": tools})

    # 3) tools/call  —> dispatch to your Python functions and wrap result
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return rpc_error(id_, -32602, "Missing 'name' in tools/call params")

        try:
            if name == "start_sora_job":
                result = start_sora_job(**arguments)
            elif name == "get_sora_job":
                result = get_sora_job(**arguments)
            else:
                return rpc_error(id_, -32601, f"Unknown tool '{name}'")
            # MCP JSON-RPC result shape:
            return rpc_result(id_, {"content": result})
        except Exception as e:
            return rpc_error(id_, -32000, "Tool execution failed", {"message": str(e)})

    # Unknown method
    return rpc_error(id_, -32601, f"Method '{method}' not found")




@app.route("/healthz", methods=["GET"])
def healthz():
    return _ok({"ok": True, "status": "healthy"})

def _require_auth_for_exec() -> Optional[Any]:
    # Public read-only endpoints:
    if request.method == "OPTIONS" or request.path in {
        "/", "/healthz", "/tools", "/mcp/tools", "/schema.json", "/.well-known/mcp.json"
    }:
        return None
    # Execution endpoints require token if set:
    if ACCESS_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth == ACCESS_TOKEN or auth == f"Bearer {ACCESS_TOKEN}":
            return None
        return _err("Unauthorized", 401)
    return None

@app.get("/schema.json")
def schema_json():
    return _ok({
        "name": "sora-mcp",
        "version": "1.0.0",
        "endpoints": {"tools": "/tools", "run": "/tools/call"},
        "tools": [t["name"] for t in _tool_list_payload()["tools"]],
    })

@app.get("/.well-known/mcp.json")
def well_known_schema():
    return schema_json()


# -----------------------------
# Catalog endpoints
# -----------------------------
@app.get("/tools")
def tools_alias_get():
    return _ok(_tool_list_payload())

@app.get("/mcp/tools")
def tools_mcp_get():
    return tools_alias_get()


# -----------------------------
# Execute endpoints
# -----------------------------
@app.post("/tools/call")
def tools_call_alias():
    maybe = _require_auth_for_exec()
    if maybe is not None:
        return maybe
    return _run_tool_impl()

@app.post("/mcp/run")
def mcp_run():
    maybe = _require_auth_for_exec()
    if maybe is not None:
        return maybe
    return _run_tool_impl()

def _run_tool_impl():
    auth = request.headers.get("Authorization", "")
    print(f"[MCP] {request.method} {request.path} Auth:{auth[:20]}...")

    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return _err("Invalid JSON body", 400)

    name = body.get("name") or body.get("tool")
    args  = body.get("arguments") or body.get("input") or {}

    if not name:
        return _err("Missing 'name' (tool)", 400)

    try:
        if name == "start_sora_job":
            # call the decorated function (if FastMCP is installed) or fallback impl
            result = start_sora_job(**args) if _FASTMCP_AVAILABLE else start_sora_job(**args)
            return _ok({"ok": True, "result": result})
        elif name == "get_sora_job":
            result = get_sora_job(**args) if _FASTMCP_AVAILABLE else get_sora_job(**args)
            return _ok({"ok": True, "result": result})
        else:
            return _err(f"Unknown tool '{name}'", 404)

    except httpx.HTTPError as e:
        return _err(f"Upstream error: {str(e)}", 502)
    except Exception as e:
        return _err(str(e), 400)


# -----------------------------
# Local dev entry (optional)
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
