"""Vision providers.

The VLM is a *perception* component, never the source of truth: it interprets
candidate regions produced by OpenCV / the manifest diff.  Offline, the
deterministic provider reports that no visual interpretation was performed —
and the analyzer falls back to manifest-diff detection (labelled as such).
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Protocol

import httpx
import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm.base import LLMResponse
from app.services.llm.prompts import INTERPRET_SCHEMA, interpret_prompt

log = get_logger(__name__)


class VisionProvider(Protocol):
    name: str

    def interpret_region(self, crop_a: np.ndarray, crop_b: np.ndarray, hint: dict) -> dict[str, Any]: ...

    def available(self) -> bool: ...


class DeterministicVision:
    name = "deterministic-demo"

    def available(self) -> bool:
        return True

    def interpret_region(self, crop_a, crop_b, hint) -> dict[str, Any]:
        return {
            "change_type": hint.get("change_type", "METADATA_CHANGE"),
            "old_value": hint.get("old_value"),
            "new_value": hint.get("new_value"),
            "description": hint.get("description", "No visual interpretation performed (demo mode)."),
            "confidence": 0.0,
            "source": "none",
        }


class OpenAICompatibleVision:
    name = "openai-compatible-vlm"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def available(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _encode(crop: np.ndarray) -> str:
        import cv2

        ok, buf = cv2.imencode(".png", crop)
        if not ok:
            raise ValueError("could not encode crop")
        return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()

    def interpret_region(self, crop_a, crop_b, hint) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0.0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": interpret_prompt() + f"\nCandidate hint: {json.dumps(hint)}"},
                        {"type": "image_url", "image_url": {"url": self._encode(crop_a)}},
                        {"type": "image_url", "image_url": {"url": self._encode(crop_b)}},
                    ],
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "region_interpretation", "schema": INTERPRET_SCHEMA, "strict": True},
            },
        }
        try:
            with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
            from app.services.llm.base import _parse_json

            return _parse_json(text) or {"change_type": "ANNOTATION_CHANGE", "description": text, "confidence": 0.2}
        except Exception as exc:
            log.error("vision_provider_failed", error=str(exc))
            return {"change_type": "ANNOTATION_CHANGE", "description": "vision interpretation failed",
                    "confidence": 0.0, "error": str(exc)}


def get_vision_provider() -> VisionProvider:
    if settings.vision_enabled and (settings.vision_api_key or settings.llm_api_key) and not settings.demo_mode:
        base = settings.vision_base_url or settings.llm_base_url
        key = settings.vision_api_key or settings.llm_api_key
        return OpenAICompatibleVision(base, key, settings.vision_model)
    return DeterministicVision()


def crop_region(img: np.ndarray, bbox: dict, pad: int = 10) -> np.ndarray:
    h, w = img.shape[:2]
    x1 = max(0, int(bbox.get("x", 0)) - pad)
    y1 = max(0, int(bbox.get("y", 0)) - pad)
    x2 = min(w, int(bbox.get("x", 0) + bbox.get("width", 0)) + pad)
    y2 = min(h, int(bbox.get("y", 0) + bbox.get("height", 0)) + pad)
    return img[y1:y2, x1:x2]


def save_crop_png(crop: np.ndarray, path: Path) -> None:
    import cv2

    cv2.imwrite(str(path), crop)
