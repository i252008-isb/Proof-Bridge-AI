"""Abstract provider interfaces for LLM, embeddings, and vision access."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class BaseLLMProvider(ABC):
    """Interface every LLM provider must implement."""

    name: str = "base"
    is_mock: bool = False

    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """Return free-form text from the LLM."""

    @abstractmethod
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        """Return a validated instance of *response_model* from the LLM's JSON output."""


class BaseEmbeddingsProvider(ABC):
    """Interface every embeddings provider must implement."""

    name: str = "base"
    dimensions: int = 0
    is_mock: bool = False

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one normalized embedding per input text."""

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


class VisionImage(BaseModel):
    """One image submitted to a vision provider.

    ``media_type`` is e.g. "image/png" or "image/jpeg"; ``label`` is a
    short reference (like "customer_photo") used by the provider prompt.
    """

    model_config = {"extra": "forbid"}

    image_bytes: bytes
    media_type: str = "image/jpeg"
    label: str = "image"


class BaseVisionProvider(ABC):
    """Interface every vision provider must implement.

    Vision providers interpret visual content. OCR is separate: OCR reads
    text, vision describes what is visible.
    """

    name: str = "base"
    is_mock: bool = False

    @abstractmethod
    def analyze_images(
        self,
        images: list[VisionImage],
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        """Return a validated instance of *response_model* describing the images."""

    def analyze_image(
        self,
        image: VisionImage,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModelT],
    ) -> ResponseModelT:
        return self.analyze_images([image], system_prompt, user_prompt, response_model)
