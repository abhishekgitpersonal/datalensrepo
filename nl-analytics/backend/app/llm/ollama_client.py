"""Thin async Ollama client."""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ..config import settings


class OllamaError(Exception):
    pass


async def generate(
    prompt: str,
    model: str,
    *,
    system: str | None = None,
    temperature: float = 0.1,
    json_mode: bool = False,
    keep_alive: str | None = None,
) -> str:
    """Non-streaming generation; returns full text."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    elif settings.ollama_keep_alive:
        payload["keep_alive"] = settings.ollama_keep_alive
    timeout = httpx.Timeout(settings.ollama_timeout_seconds, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.post(f"{settings.ollama_host}/api/generate", json=payload)
        except httpx.HTTPError as e:
            raise OllamaError(f"Could not reach Ollama at {settings.ollama_host}: {e}") from e
        if r.status_code != 200:
            raise OllamaError(f"Ollama returned {r.status_code}: {r.text[:300]}")
        data = r.json()
        return data.get("response", "")


async def generate_stream(
    prompt: str,
    model: str,
    *,
    system: str | None = None,
    temperature: float = 0.2,
    keep_alive: str | None = None,
) -> AsyncIterator[str]:
    """Stream token chunks from Ollama."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    elif settings.ollama_keep_alive:
        payload["keep_alive"] = settings.ollama_keep_alive
    timeout = httpx.Timeout(settings.ollama_timeout_seconds, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream("POST", f"{settings.ollama_host}/api/generate", json=payload) as r:
                if r.status_code != 200:
                    text = await r.aread()
                    raise OllamaError(f"Ollama {r.status_code}: {text[:300]!r}")
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "response" in obj and obj["response"]:
                        yield obj["response"]
                    if obj.get("done"):
                        break
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama stream error: {e}") from e
