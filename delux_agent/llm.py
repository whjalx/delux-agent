from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    raw: dict
    provider: str = "openai"


class LLMError(RuntimeError):
    pass


def _parse_sse_line(line: str) -> tuple[str, bool]:
    if not line.startswith("data: "):
        return "", False
    payload = line[6:]
    if payload.strip() == "[DONE]":
        return "", True
    try:
        obj = json.loads(payload)
        delta = obj.get("choices", [{}])[0].get("delta", {})
        return delta.get("content", "") or "", False
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return "", False


def _stream_with_timeout(response, on_chunk=None, timeout=8) -> str | None:
    result = {"text": "", "done": False}

    def _reader():
        while True:
            try:
                line_bytes = response.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
                content, done = _parse_sse_line(line)
                if content:
                    result["text"] += content
                    if on_chunk:
                        on_chunk(content)
                if done:
                    result["done"] = True
                    return
            except Exception:
                break

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None
    return result["text"] if result["done"] or result["text"] else None


def _do_request(url: str, headers: dict, payload: dict, timeout: int, stream: bool = False, on_chunk=None) -> LLMResponse:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    response = urllib.request.urlopen(request, timeout=timeout)
    if stream:
        # Use a generous streaming timeout — some models need time to start generating
        stream_timeout = max(timeout, 30)
        text = _stream_with_timeout(response, on_chunk=on_chunk, timeout=stream_timeout)
        if text is None:
            payload.pop("stream", None)
            result = _do_request(url, headers, payload, timeout, stream=False)
            return result
        return LLMResponse(text=text, raw={})
    else:
        raw = json.loads(response.read().decode("utf-8"))
        text = raw["choices"][0]["message"]["content"]
        return LLMResponse(text=text, raw=raw)


def chat_completion(
    api_base: str,
    api_key: str | None,
    model: str,
    messages: list[dict[str, str]],
    api_endpoint: str | None = None,
    timeout: int = 180,
    stream: bool = False,
    on_chunk=None,
    max_tokens: int | None = None,
) -> LLMResponse:
    url = api_endpoint or (api_base.rstrip("/") + "/chat/completions")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if stream:
        payload["stream"] = True
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    
    # --- GOOGLE GEMINI NATIVE SUPPORT ---
    if api_base == "google" or "generativelanguage.googleapis.com" in (api_endpoint or api_base):
        # Use v1beta for access to newest models
        google_url = api_endpoint or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        # Map OpenAI messages to Google contents
        contents = []
        system_instruction = None
        
        for m in messages:
            role = m["role"]
            content = m["content"]
            if role == "system":
                system_instruction = {"parts": [{"text": content}]}
            else:
                google_role = "user" if role == "user" else "model"
                contents.append({"role": google_role, "parts": [{"text": content}]})
        
        google_payload = {"contents": contents}
        if system_instruction:
            google_payload["system_instruction"] = system_instruction
        if max_tokens:
            google_payload["generationConfig"] = {"maxOutputTokens": max_tokens, "temperature": 0.2}
        else:
            google_payload["generationConfig"] = {"temperature": 0.2}

        try:
            req = urllib.request.Request(google_url, data=json.dumps(google_payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
                text = raw.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return LLMResponse(text=text, raw=raw, provider="google")
        except Exception as e:
            if hasattr(e, "read"):
                body = e.read().decode("utf-8", errors="replace")
                raise LLMError(f"Google API Error: {body}") from e
            raise LLMError(f"Google API connection failed: {str(e)}") from e

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        if stream:
            result = _do_request(url, headers, payload, timeout, stream=True, on_chunk=on_chunk)
            if result is None:
                payload.pop("stream", None)
                result = _do_request(url, headers, payload, timeout, stream=False)
            return result
        else:
            return _do_request(url, headers, payload, timeout, stream=False)
    except socket.timeout:
        raise LLMError(
            f"Request timed out after {timeout}s. "
            f"Check if your LLM endpoint is running: {url}"
        ) from None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"LLM HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
        raise LLMError(
            f"LLM connection failed to {url}: {reason}. "
            f"Check if the endpoint is running and accessible."
        ) from exc
    except TimeoutError:
        raise LLMError(
            f"Request timed out after {timeout}s. "
            f"Check if your LLM endpoint is running: {url}"
        ) from None
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected LLM response format") from exc


def get_embedding(
    api_base: str,
    api_key: str | None,
    model: str,
    text: str,
    api_endpoint: str | None = None,
    timeout: int = 30,
) -> list[float]:
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
    
    # --- GOOGLE GEMINI NATIVE SUPPORT ---
    if api_base == "google" or "generativelanguage.googleapis.com" in (api_endpoint or api_base):
        google_url = api_endpoint or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={api_key}"
        google_payload = {
            "content": {
                "parts": [{"text": text}]
            }
        }
        try:
            req = urllib.request.Request(google_url, data=json.dumps(google_payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
                return raw["embedding"]["values"]
        except Exception as e:
            if hasattr(e, "read"):
                body = e.read().decode("utf-8", errors="replace")
                raise LLMError(f"Google Embedding API Error: {body}") from e
            raise LLMError(f"Google Embedding API connection failed: {str(e)}") from e

    # --- OPENAI / COMPATIBLE SUPPORT ---
    url = api_endpoint or (api_base.rstrip("/") + "/embeddings")
    payload = {
        "model": model,
        "input": text,
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
            return raw["data"][0]["embedding"]
    except socket.timeout:
        raise LLMError(
            f"Embedding request timed out after {timeout}s. "
            f"Check if your embedding endpoint is running: {url}"
        ) from None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LLMError(f"Embedding LLM HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        reason = str(exc.reason) if hasattr(exc, "reason") else str(exc)
        raise LLMError(
            f"Embedding LLM connection failed to {url}: {reason}. "
            f"Check if the endpoint is running and accessible."
        ) from exc
    except TimeoutError:
        raise LLMError(
            f"Embedding request timed out after {timeout}s. "
            f"Check if your embedding endpoint is running: {url}"
        ) from None
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected Embedding response format") from exc

