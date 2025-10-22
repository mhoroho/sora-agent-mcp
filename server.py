from flask import Flask, request, jsonify
import os, requests

app = Flask(__name__)

SORA_API_BASE = os.getenv("SORA_API_BASE", "https://api.openai.com/v1")
SORA_API_KEY  = os.getenv("SORA_API_KEY") or os.getenv("OPENAI_API_KEY")
MODEL_ID = os.getenv("SORA_MODEL_ID", "sora-2")

# ---- MCP tool catalog ----
@app.get("/mcp/tools")
def list_tools():
    return jsonify({
        "tools": [
            {
                "name": "start_sora_job",
                "description": "Create a Sora video generation job",
                "input_schema": {
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
                "input_schema": {
                    "type": "object",
                    "properties": {"job_id": {"type": "string"}},
                    "required": ["job_id"]
                }
            }
        ]
    })

# ---- MCP executor ----
@app.post("/mcp/run")
def run_tool():
    body = request.get_json(force=True)
    name = body.get("name")
    args = body.get("arguments", {})

    headers = {
        "Authorization": f"Bearer {SORA_API_KEY}",
        "Content-Type": "application/json"
    }

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
        r = requests.post(f"{SORA_API_BASE}/video/jobs", headers=headers, json=payload)
        return jsonify({"ok": True, "result": r.json()})

    elif name == "get_sora_job":
        job_id = args.get("job_id")
        r = requests.get(f"{SORA_API_BASE}/video/jobs/{job_id}", headers=headers)
        data = r.json()
        result = {
            "status": data.get("status"),
            "progress": data.get("progress"),
            "video_url": (data.get("output", {}).get("assets", [{}])[0].get("url")
                          if data.get("output") else None),
            "thumbnail_url": data.get("output", {}).get("thumbnail_url"),
            "raw": data
        }
        return jsonify({"ok": True, "result": result})

    else:
        return jsonify({"ok": False, "error": f"Unknown tool {name}"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
