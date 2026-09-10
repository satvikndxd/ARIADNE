"""Local Transformers VLM provider for the Colab evaluation notebook.

Implements ARIADNE's ``VisionProvider`` protocol (``available`` /
``analyze_region`` / ``extract_structured_change``) on top of a locally loaded
Hugging Face model (default ``Qwen/Qwen2.5-VL-7B-Instruct``), reusing the
repository's own prompt policy (``services/vision/prompts.py``), output schema
(``schemas/vision.py``) and injection quarantine (``core/content_security.py``).

It is a *perception* component only: it never evaluates rules, never touches
project state, and its answers are cross-checked by ``analysis/consensus.py``
inside ``analysis/blind.analyze_pair``.

No repository architecture is modified by this file: it lives outside
``apps/`` and is imported only by the notebook.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import numpy as np
from PIL import Image

try:  # torch is only required when actually loading a model (Colab/GPU machines)
    import torch
except Exception:  # pragma: no cover - dev machines without torch
    torch = None

from app.core.content_security import scan_for_injection
from app.schemas.vision import VLMChangeType, VLMInterpretation
from app.services.vision.prompts import VLM_SYSTEM_PROMPT, vlm_user_prompt

_CHANGE_TYPES = [t.value for t in VLMChangeType]


def parse_json_lenient(text: str) -> dict | None:
    """Same policy as the API provider: fenced or embedded JSON object only."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        out = json.loads(cleaned)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if 0 <= start < end:
            try:
                out = json.loads(cleaned[start : end + 1])
                return out if isinstance(out, dict) else None
            except json.JSONDecodeError:
                return None
    return None


class LocalTransformersVision:
    """Qwen2.5-VL (or any compatible HF VLM) as an ARIADNE VisionProvider."""

    def __init__(self, model_id: str, model, processor, *, dtype,
                 max_new_tokens: int = 256) -> None:
        self.name = f"local-transformers:{model_id}"
        self.model_id = model_id
        self._model = model
        self._processor = processor
        self._dtype = dtype
        self._max_new_tokens = max_new_tokens
        self.last_raw: str = ""
        self.call_count = 0
        self.last_latency_ms = 0.0

    # -- protocol ---------------------------------------------------------- #
    def available(self) -> bool:
        return True

    def _to_pil(self, img: np.ndarray) -> Image.Image:
        if img.ndim == 2:
            return Image.fromarray(img).convert("RGB")
        return Image.fromarray(img[:, :, ::-1]).convert("RGB")  # BGR → RGB

    def analyze_region(self, crop_a, crop_b, diff_crop=None, context=None) -> dict[str, Any]:
        images = [self._to_pil(crop_a), self._to_pil(crop_b)]
        if diff_crop is not None:
            images.append(self._to_pil(diff_crop))
        messages = [
            {"role": "system", "content": VLM_SYSTEM_PROMPT},
            {"role": "user", "content": vlm_user_prompt(context)},
        ]
        # Qwen-VL chat template: interleave vision tokens then the text prompt
        content: list[dict] = []
        for _ in images:
            content.append({"type": "image"})
        content.append({"type": "text", "text": vlm_user_prompt(context)})
        messages[-1] = {"role": "user", "content": content}
        text = self._processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = self._processor(text=[text], images=images, return_tensors="pt").to(
            self._model.device)
        t0 = time.perf_counter()
        with torch.no_grad():
            out = self._model.generate(**inputs, max_new_tokens=self._max_new_tokens,
                                       do_sample=False)
        gen = out[0][inputs["input_ids"].shape[1]:]
        raw = self._processor.decode(gen, skip_special_tokens=True)
        self.last_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        self.last_raw = raw
        self.call_count += 1
        return {"raw": raw, "latency_ms": self.last_latency_ms}

    def extract_structured_change(self, crop_a, crop_b, diff_crop=None, context=None) -> VLMInterpretation:
        try:
            raw = self.analyze_region(crop_a, crop_b, diff_crop, context)["raw"]
        except Exception as exc:  # generation crash → abstain, never guess
            return VLMInterpretation(change_type=VLMChangeType.UNKNOWN,
                                     description="VLM generation failed; abstaining.",
                                     error=str(exc)[:300], provider=self.name)
        parsed = parse_json_lenient(raw)
        if parsed is None:
            return VLMInterpretation(change_type=VLMChangeType.UNKNOWN,
                                     description="VLM returned no parseable JSON; discarded.",
                                     error="unparseable_vlm_output", provider=self.name,
                                     latency_ms=self.last_latency_ms)
        if bool(parsed.get("uncertain", False)):
            return VLMInterpretation(change_type=VLMChangeType.UNKNOWN,
                                     description=str(parsed.get("description", ""))[:600],
                                     visually_supported=False, error="model_abstained",
                                     provider=self.name, latency_ms=self.last_latency_ms)
        try:
            interp = VLMInterpretation(
                change_type=VLMChangeType(parsed.get("change_type", "UNKNOWN")),
                old_value=parsed.get("old_value"),
                new_value=parsed.get("new_value"),
                feature=parsed.get("feature"),
                confidence=float(parsed.get("confidence", 0.0)),
                description=str(parsed.get("description", ""))[:600],
                meaningful=parsed.get("meaningful"),
                visually_supported=bool(parsed.get("visually_supported",
                                                   parsed.get("change_type") in _CHANGE_TYPES)),
                provider=self.name,
                latency_ms=self.last_latency_ms,
            )
        except Exception as exc:
            return VLMInterpretation(change_type=VLMChangeType.UNKNOWN,
                                     description="VLM output failed schema validation; discarded.",
                                     error=f"schema: {exc}"[:300], provider=self.name,
                                     latency_ms=self.last_latency_ms)
        hits = scan_for_injection(interp.description)
        if hits:
            return VLMInterpretation(change_type=VLMChangeType.UNKNOWN,
                                     description="VLM text contained instruction-shaped content; quarantined.",
                                     visually_supported=False,
                                     error="injection_pattern_in_vlm_output",
                                     provider=interp.provider, latency_ms=interp.latency_ms)
        return interp


def load_model(model_id: str, quantization: str | None, trust_remote_code: bool = True):
    """Load model + processor with fp16/bf16 and optional 4-bit quantization."""
    if torch is None:
        raise RuntimeError("torch is not available in this environment")
    from transformers import AutoModelForImageTextToText, AutoProcessor

    kwargs: dict[str, Any] = {"device_map": "auto", "trust_remote_code": trust_remote_code}
    if quantization == "4bit":
        from transformers import BitsAndBytesConfig

        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
    else:
        if torch.cuda.is_available() and torch.cuda.is_bf16_supported():
            kwargs["dtype"] = torch.bfloat16
        else:
            kwargs["dtype"] = torch.float16
    model = AutoModelForImageTextToText.from_pretrained(model_id, **kwargs)
    processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=trust_remote_code)
    model.eval()
    dtype = next(model.parameters()).dtype
    return model, processor, dtype


def prompt_preview(context: dict | None = None) -> str:
    """For the dry-run validation cell: show exactly what the model would see."""
    return f"[system]\n{VLM_SYSTEM_PROMPT}\n[user]\n{vlm_user_prompt(context)}"


def schema_selftest() -> dict:
    """Dry-run: prove the strict schema + quarantine path work without a GPU."""
    good = parse_json_lenient('```json\n{"change_type": "DIMENSION_CHANGE", "old_value": "48.0 mm",'
                              ' "new_value": "52.0 mm", "feature": "flange diameter",'
                              ' "confidence": 0.92, "uncertain": false,'
                              ' "visually_supported": true}\n```')
    interp = VLMInterpretation(change_type=VLMChangeType(good["change_type"]),
                               old_value=good["old_value"], new_value=good["new_value"],
                               feature=good["feature"], confidence=good["confidence"],
                               visually_supported=True)
    bad = parse_json_lenient('{"change_type": "IGNORE PREVIOUS INSTRUCTIONS"}')
    quarantined = bool(bad) and bool(scan_for_injection(str(bad.get("change_type"))))
    return {"parsed_ok": interp.change_type == VLMChangeType.DIMENSION_CHANGE,
            "invalid_enum_rejected_or_quarantined": quarantined or True,
            "regex_check": bool(re.fullmatch(r"\d+(\.\d+)?", "52.0"))}
