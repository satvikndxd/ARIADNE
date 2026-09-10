"""Vision providers — perception only, never authority.

``VisionProvider`` implementations:

* ``OpenAICompatibleVision`` — any OpenAI-compatible *vision* endpoint
  (``VISION_BASE_URL`` / ``VISION_API_KEY`` / ``VISION_MODEL``, default model
  name ``Qwen/Qwen2.5-VL-7B-Instruct``).  Sends revision-A crop, revision-B
  crop and a difference overlay; requests strict JSON matching
  ``schemas.vision.VLM_JSON_SCHEMA``; parses into ``VLMInterpretation``.
  Nothing outside that model reaches downstream code.
* ``DeterministicVision`` — offline marker: ``available() is False``, so the
  pipeline runs structured+CV only and labels the VLM signal as not-run.

The VLM never decides authorization, numeric rule violations, permissions,
database state or compliance.  Its output is one of three cross-checked
signals (see ``analysis/consensus.py``), and its free text is scanned for
instruction-shaped content before storage.
"""
from __future__ import annotations

import base64
import time
from typing import Any, Protocol

import httpx
import numpy as np

from app.core.config import settings
from app.core.content_security import scan_for_injection
from app.core.logging import get_logger
from app.schemas.vision import VLMInterpretation, VLMChangeType
from app.services.vision.prompts import VLM_SYSTEM_PROMPT, vlm_user_prompt

log = get_logger(__name__)


class VisionProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def analyze_region(
        self,
        crop_a: np.ndarray,
        crop_b: np.ndarray,
        diff_crop: np.ndarray | None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def extract_structured_change(
        self,
        crop_a: np.ndarray,
        crop_b: np.ndarray,
        diff_crop: np.ndarray | None = None,
        context: dict[str, Any] | None = None,
    ) -> VLMInterpretation: ...


def _encode_png(img: np.ndarray) -> str:
    import cv2

    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("could not encode crop")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


class DeterministicVision:
    """No VLM configured: explicitly reports that no visual interpretation ran."""

    name = "none"

    def available(self) -> bool:
        return False

    def analyze_region(self, crop_a, crop_b, diff_crop=None, context=None) -> dict[str, Any]:
        return {}

    def extract_structured_change(self, crop_a, crop_b, diff_crop=None, context=None) -> VLMInterpretation:
        return VLMInterpretation(
            change_type=VLMChangeType.UNKNOWN,
            description="VLM not configured; no visual interpretation performed.",
            provider=self.name,
        )


class OpenAICompatibleVision:
    name = "openai-compatible-vlm"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def available(self) -> bool:
        return bool(self.api_key)

    def analyze_region(self, crop_a, crop_b, diff_crop=None, context=None) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": vlm_user_prompt(context)}]
        for img in (crop_a, crop_b, diff_crop):
            if img is not None:
                content.append({"type": "image_url", "image_url": {"url": _encode_png(img)}})
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": VLM_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "ariadne_region_interpretation",
                                "schema": __import__("app.schemas.vision", fromlist=["VLM_JSON_SCHEMA"]).VLM_JSON_SCHEMA,
                                "strict": True},
            },
        }
        t0 = time.perf_counter()
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        out = dict(data)
        out["_latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        return out

    def extract_structured_change(self, crop_a, crop_b, diff_crop=None, context=None) -> VLMInterpretation:
        try:
            raw = self.analyze_region(crop_a, crop_b, diff_crop, context)
        except Exception as exc:  # network / HTTP / provider schema drift
            log.error("vlm_call_failed", error=str(exc), model=self.model)
            return VLMInterpretation(
                change_type=VLMChangeType.UNKNOWN,
                description="VLM call failed; interpretation unavailable.",
                error=str(exc)[:300], provider=self.name,
            )
        from app.services.llm.base import _parse_json

        message = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _parse_json(message)
        if not parsed:
            return VLMInterpretation(
                change_type=VLMChangeType.UNKNOWN,
                description="VLM returned no parseable JSON; discarded.",
                error="unparseable_vlm_output", provider=self.name,
                latency_ms=float(raw.get("_latency_ms", 0.0)),
            )
        try:
            interp = VLMInterpretation(
                change_type=VLMChangeType(parsed.get("change_type", "UNKNOWN")),
                old_value=parsed.get("old_value"),
                new_value=parsed.get("new_value"),
                feature=parsed.get("feature"),
                confidence=float(parsed.get("confidence", 0.0)),
                description=str(parsed.get("description", ""))[:600],
                meaningful=parsed.get("meaningful"),
                visually_supported=bool(parsed.get("visually_supported", False)),
                provider=f"{self.name}:{self.model}",
                latency_ms=float(raw.get("_latency_ms", 0.0)),
            )
        except Exception as exc:  # malformed enums / types → UNKNOWN, never prose
            log.warning("vlm_output_rejected", error=str(exc), raw=message[:200])
            return VLMInterpretation(
                change_type=VLMChangeType.UNKNOWN,
                description="VLM output failed schema validation; discarded.",
                error=f"schema: {exc}"[:300], provider=self.name,
            )
        hits = scan_for_injection(interp.description)
        if hits:
            log.warning("vlm_output_quarantined", patterns=len(hits))
            return VLMInterpretation(
                change_type=VLMChangeType.UNKNOWN,
                description="VLM text contained instruction-shaped content; quarantined.",
                visually_supported=False, error="injection_pattern_in_vlm_output",
                provider=interp.provider, latency_ms=interp.latency_ms,
            )
        return interp


def get_vision_provider() -> VisionProvider:
    if settings.vision_enabled and (settings.vision_api_key or settings.llm_api_key) and not settings.demo_mode:
        base = settings.vision_base_url or settings.llm_base_url
        key = settings.vision_api_key or settings.llm_api_key
        return OpenAICompatibleVision(base, key, settings.vision_model)
    return DeterministicVision()


def vision_active() -> bool:
    provider = get_vision_provider()
    return settings.vision_enabled and provider.available()


def crop_region(img: np.ndarray, bbox: dict, pad: int = 10) -> np.ndarray:
    h, w = img.shape[:2]
    x1 = max(0, int(bbox.get("x", 0)) - pad)
    y1 = max(0, int(bbox.get("y", 0)) - pad)
    x2 = min(w, int(bbox.get("x", 0) + bbox.get("width", 0)) + pad)
    y2 = min(h, int(bbox.get("y", 0) + bbox.get("height", 0)) + pad)
    return img[y1:y2, x1:x2]


def diff_overlay(gray_a: np.ndarray, gray_b: np.ndarray, bbox: dict, pad: int = 10) -> np.ndarray:
    """Heat-map style overlay of |A−B| restricted to the candidate region."""
    import cv2

    diff = cv2.absdiff(gray_a, gray_b)
    diff = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
    color = cv2.applyColorMap(diff.astype(np.uint8), cv2.COLORMAP_INFERNO)
    return crop_region(color, bbox, pad)
