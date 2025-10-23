"""
Sora MCP (FastMCP) — quickstart-style server

Run (stdio mode, like the quickstart):
    uv run server sora_fastmcp stdio
"""

import os
from typing import Optional, Dict, Any

import httpx
from mcp.server.fastmcp import FastMCP

# ---- Config via env ----
SORA_API_BASE = os.getenv("SORA_API_BASE", "https://api.openai.com/v1")
SORA_API_KEY  = os.getenv("SORA_API_KEY") or os.getenv("OPENAI_API_KEY")
SORA_MODEL_ID = os.getenv("SORA_MODEL_ID", "sora-2")
HTTP_TIMEOUT  = float(os.getenv("HTTP_TIMEOUT", "60"))

# Create an MCP server
mcp = FastMCP("Sora MCP")


# ---- Tools ----

@mcp.tool()
def start_sora_job(
    prompt: str,
    duration: float = 12,
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
    audio: bool = True,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a Sora video generation job.
    Returns upstream JSON (job id/status/etc.).
    """
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
        r.raise_for_status()
        return r.json()


@mcp.tool()
def get_sora_job(job_id: str) -> Dict[str, Any]:
    """
    Poll a Sora job and return normalized status + asset URLs.
    """
    if not SORA_API_KEY:
        raise RuntimeError("Missing SORA_API_KEY or OPENAI_API_KEY")

    headers = {"Authorization": f"Bearer {SORA_API_KEY}"}

    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        r = client.get(f"{SORA_API_BASE}/video/jobs/{job_id}", headers=headers)
        r.raise_for_status()
        data = r.json()

    # Normalize a few useful fields while returning the raw too
    video_url = None
    assets = (data.get("output") or {}).get("assets") or []
    if assets and isinstance(assets, list):
        video_url = (assets[0] or {}).get("url")

    return {
        "status": data.get("status"),
        "progress": data.get("progress"),
        "video_url": video_url,
        "thumbnail_url": (data.get("output") or {}).get("thumbnail_url"),
        "raw": data,
    }


# ---- Optional: an example resource (not required) ----

@mcp.resource("sora://job/{job_id}")
def sora_job_resource(job_id: str) -> str:
    """A small resource example that formats a status lookup hint."""
    return f"Use get_sora_job with job_id={job_id} to retrieve status and assets."


# ---- Optional: a prompt helper (not required) ----

@mcp.prompt()
def build_sora_prompt(
    scene: str,
    camera: str = "static",
    duration: float = 12,
    aspect_ratio: str = "16:9",
    resolution: str = "1080p",
    audio: bool = True,
    negatives: str = "",
) -> str:
    """Generate a structured Sora prompt directive from parts."""
    lines = [
        f"Scene: {scene}",
        f"Camera/motion: {camera}",
        f"Duration: {duration}s",
        f"Aspect ratio: {aspect_ratio}",
        f"Resolution: {resolution}",
        f"Audio: {'on' if audio else 'off'}",
    ]
    if negatives:
        lines.append(f"Negative constraints: {negatives}")
    return "\n".join(lines)


# ---- Entrypoint (stdio, like the quickstart) ----
if __name__ == "__main__":
    # runs an MCP stdio server (the same mode used in the quickstart snippet)
    mcp.run_stdio()
