"""Thin, resilient wrapper around the official google-genai SDK returning Pydantic-validated JSON."""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from typing import TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

import config

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}
MODEL_UNAVAILABLE_CODES = {404}


class GeminiError(RuntimeError):
    """Raised when Gemini cannot produce a valid response. Message never contains secrets."""


def _strip_json(text: str) -> str:
    text = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return fence.group(1) if fence else text


class GeminiClient:
    _lock = threading.Lock()

    def __init__(self, model: str | None = None) -> None:
        if not config.GEMINI_API_KEY:
            raise GeminiError("GEMINI_API_KEY is not configured. Add it to your .env file.")
        self.client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=config.GEMINI_TIMEOUT_SECONDS * 1000),
        )
        primary = model or config.GEMINI_MODEL
        self.models = [primary] + [m for m in config.GEMINI_FALLBACK_MODELS if m != primary]
        self._model_index = 0
        self.call_count = 0

    @property
    def model(self) -> str:
        return self.models[self._model_index]

    def _advance_model(self) -> bool:
        if self._model_index + 1 < len(self.models):
            self._model_index += 1
            log.warning("Switching Gemini model to %s", self.model)
            return True
        return False

    def generate_structured(
        self,
        *,
        schema: type[T],
        system: str,
        contents: list,
        temperature: float = 0.3,
    ) -> T:
        last_error = "unknown error"
        unavailable_streak = 0
        for attempt in range(config.GEMINI_MAX_RETRIES):
            try:
                self.call_count += 1
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=temperature,
                    ),
                )
                parsed = response.parsed
                if isinstance(parsed, schema):
                    return parsed
                return schema.model_validate_json(_strip_json(response.text or ""))
            except genai_errors.APIError as exc:
                code = getattr(exc, "code", None) or 0
                last_error = f"Gemini API error {code}: {getattr(exc, 'message', '') or exc.__class__.__name__}"
                if code in MODEL_UNAVAILABLE_CODES:
                    if not self._advance_model():
                        break
                    continue
                if code in RETRYABLE_CODES:
                    unavailable_streak += 1
                    if unavailable_streak >= 2 and self._advance_model():
                        unavailable_streak = 0
                    delay = min(30.0, (2 ** attempt) + random.uniform(0, 1))
                    if code == 429:
                        delay = max(delay, 5.0)
                    time.sleep(delay)
                    continue
                raise GeminiError(last_error) from None
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                last_error = f"Gemini returned invalid structured output: {str(exc)[:200]}"
                time.sleep(1)
                continue
            except Exception as exc:  # network / timeout errors from httpx
                last_error = f"Gemini request failed: {exc.__class__.__name__}"
                time.sleep(min(20.0, 2 ** attempt))
                continue
        raise GeminiError(last_error)

    @staticmethod
    def image_part(jpeg_bytes: bytes) -> types.Part:
        return types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg")
