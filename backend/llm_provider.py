"""LLMProvider — Gemini primary, Groq fallback, local-mock for tests (M1).

No API keys in this environment -> MockProvider (offline, deterministic).
Keys are requested at Phase 2 gate; Gemini/Groq SDKs import lazily so the
module loads without them installed.
"""
import os


class LLMError(RuntimeError):
    pass


class BaseProvider:
    name = "base"

    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class MockProvider(BaseProvider):
    """Deterministic stand-in. Tests preload `responses`; default = empty JSON array."""

    name = "mock"

    def __init__(self, responses: list[str] | None = None):
        self.responses = list(responses or [])
        self.calls: list[str] = []

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.responses:
            return self.responses.pop(0)
        return "[]"


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-3.5-flash-lite"):
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str) -> str:
        try:
            from google import genai
        except ImportError as e:
            raise LLMError("google-genai not installed") from e
        client = genai.Client(api_key=self.api_key)
        try:
            resp = client.models.generate_content(model=self.model, contents=prompt)
        except Exception as e:
            raise LLMError(f"gemini call failed: {e}") from e
        return (resp.text or "").strip()


class GroqProvider(BaseProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str = "openai/gpt-oss-20b"):
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str) -> str:
        try:
            from groq import Groq
        except ImportError as e:
            raise LLMError("groq SDK not installed") from e
        client = Groq(api_key=self.api_key)
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
        except Exception as e:
            raise LLMError(f"groq call failed: {e}") from e
        return (resp.choices[0].message.content or "").strip()


class FailoverProvider(BaseProvider):
    """Gemini, then Groq on failure (M1). Raises only if both fail."""

    name = "failover"

    def __init__(self, primary: BaseProvider, fallback: BaseProvider):
        self.primary = primary
        self.fallback = fallback

    def generate(self, prompt: str) -> str:
        try:
            return self.primary.generate(prompt)
        except LLMError:
            return self.fallback.generate(prompt)


def get_provider(explicit: BaseProvider | None = None) -> BaseProvider | None:
    """Return a provider, or None when no keys are configured (offline fallback path).

    Set LLM_PROVIDER=mock in tests to force determinism even if keys exist.
    """
    if explicit is not None:
        return explicit
    if os.environ.get("LLM_PROVIDER", "").lower() == "mock":
        return MockProvider()
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if gemini_key and groq_key:
        return FailoverProvider(GeminiProvider(gemini_key), GroqProvider(groq_key))
    if gemini_key:
        return GeminiProvider(gemini_key)
    if groq_key:
        return GroqProvider(groq_key)
    return None
