"""Deterministic offline providers for demo mode and tests.

Mock outputs are clearly identifiable as mock/heuristic data and never echo
prompt or document content: chat results are content hashes and generated
JSON is filled from field introspection using only a prompt digest.
"""

from __future__ import annotations

import hashlib
import re
import types
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Union, get_args, get_origin

import numpy as np
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from proofbridge_ai.exceptions import ProviderResponseValidationError
from proofbridge_ai.logging_utils import get_logger, redact
from proofbridge_ai.providers.base import (
    BaseEmbeddingsProvider,
    BaseLLMProvider,
    BaseVisionProvider,
    VisionImage,
)

logger = get_logger("providers.mock")


def _fill_field(field_name: str, field: FieldInfo, prompt_digest: str) -> Any:
    if not field.is_required():
        return field.get_default(call_default_factory=True)
    return _fill_annotation(field_name, field.annotation, prompt_digest)


def _fill_annotation(field_name: str, annotation: Any, prompt_digest: str) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Union or origin is types.UnionType:
        return None
    if origin is Literal:
        return args[0]
    if origin is not None:
        if origin is dict:
            return {}
        if origin in (list, set, frozenset, tuple):
            return []
    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return next(iter(annotation))
        if issubclass(annotation, BaseModel):
            return {
                name: _fill_field(name, sub_field, prompt_digest)
                for name, sub_field in annotation.model_fields.items()
            }
        if issubclass(annotation, str):
            return f"mock {field_name} (prompt {prompt_digest})"
        if issubclass(annotation, bool):
            return False
        if issubclass(annotation, int):
            return 1
        if issubclass(annotation, float):
            return 0.5
        if issubclass(annotation, datetime):
            return datetime.now(timezone.utc)
    return None


class MockLLMProvider(BaseLLMProvider):
    """Offline LLM stand-in producing deterministic, schema-valid placeholder data."""

    name = "mock"
    is_mock = True

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        combined = f"{system_prompt}\n{user_prompt}"
        digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]
        logger.info("mock chat prompt %s", redact(combined))
        return f"MOCK:{digest}"

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        combined = f"{system_prompt}\n{user_prompt}"
        digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]
        logger.info(
            "mock generate_json model=%s prompt %s",
            response_model.__name__,
            redact(combined),
        )
        data = {
            name: _fill_field(name, field, digest)
            for name, field in response_model.model_fields.items()
        }
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise ProviderResponseValidationError(
                f"Mock provider could not build a valid {response_model.__name__}: {exc}",
                provider=self.name,
            ) from exc


class MockEmbeddingsProvider(BaseEmbeddingsProvider):
    """Deterministic offline embeddings: seeded hash-sign vectors, 384 dimensions.

    Shared vocabulary between texts yields cosine similarity, which makes the
    offline demo behave plausibly. Results are labeled heuristic by consumers.
    """

    name = "mock"
    dimensions = 384
    is_mock = True

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = np.zeros(self.dimensions, dtype=np.float64)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimensions
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vector[index] += sign
        norm = float(np.linalg.norm(vector))
        if norm > 0.0:
            vector /= norm
        return vector.tolist()


class MockVisionProvider(BaseVisionProvider):
    """Offline vision stand-in: performs NO genuine image analysis.

    It returns schema-valid placeholder structures built from the prompt
    digest (never from image pixels) and is always labeled mock by the
    vision service. Never mistaken for genuine model output.
    """

    name = "mock"
    is_mock = True

    def analyze_images(
        self,
        images: list[VisionImage],
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        combined = f"{system_prompt}\n{user_prompt}\nimages={len(images)}"
        digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()[:12]
        logger.info(
            "mock vision analyze_images model=%s prompt %s",
            response_model.__name__,
            redact(combined),
        )
        data = {
            name: _fill_field(name, field, digest)
            for name, field in response_model.model_fields.items()
        }
        try:
            return response_model.model_validate(data)
        except ValidationError as exc:
            raise ProviderResponseValidationError(
                f"Mock vision provider could not build a valid "
                f"{response_model.__name__}: {exc}",
                provider=self.name,
            ) from exc
