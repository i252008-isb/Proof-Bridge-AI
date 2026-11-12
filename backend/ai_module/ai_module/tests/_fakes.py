"""Shared scripted provider fakes for service tests (no network)."""

from proofbridge_ai.providers.base import BaseLLMProvider, BaseVisionProvider


class FakeLLMProvider(BaseLLMProvider):
    """Scripted LLM stand-in: returns a fixed result or raises a fixed error."""

    name = "fake-llm"
    is_mock = False

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[tuple[str, str, type]] = []

    def chat(self, system_prompt, user_prompt):
        return "fake"

    def generate_json(self, system_prompt, user_prompt, response_model):
        self.calls.append((system_prompt, user_prompt, response_model))
        if self.error:
            raise self.error
        if self.result is None:
            return response_model.model_validate(
                {
                    name: field.get_default(call_default_factory=True)
                    for name, field in response_model.model_fields.items()
                }
            )
        return self.result


class FakeVisionProvider(BaseVisionProvider):
    """Scripted vision stand-in: returns a fixed result or raises an error."""

    name = "fake-vision"
    is_mock = False

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[tuple[list, str, str, type]] = []

    def analyze_images(self, images, system_prompt, user_prompt, response_model):
        self.calls.append((images, system_prompt, user_prompt, response_model))
        if self.error:
            raise self.error
        if self.result is None:
            return response_model.model_validate(
                {
                    name: field.get_default(call_default_factory=True)
                    for name, field in response_model.model_fields.items()
                }
            )
        return self.result
