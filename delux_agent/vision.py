from __future__ import annotations

import base64
import json
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VisionResult:
    ok: bool
    output: str


def _encode_image(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    data = path.read_bytes()
    return base64.b64encode(data).decode("utf-8")


def _get_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mime_map.get(ext, "image/png")


def analyze_image(
    image_path: str,
    prompt: str,
    api_base: str,
    api_key: str | None,
    model: str,
    api_endpoint: str | None = None,
    timeout: int = 60,
) -> VisionResult:
    try:
        b64 = _encode_image(image_path)
        mime = _get_mime(image_path)
    except FileNotFoundError as e:
        return VisionResult(False, str(e))

    url = api_endpoint or (api_base.rstrip("/") + "/chat/completions")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 2048,
        "temperature": 0.2,
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Delux-Agent/1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            text = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
            return VisionResult(True, text.strip())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return VisionResult(False, f"Vision API HTTP {e.code}: {body}")
    except Exception as e:
        return VisionResult(False, f"Vision analysis failed: {e}")
