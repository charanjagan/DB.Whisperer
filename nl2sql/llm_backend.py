"""LLM backend abstraction: dev Ollama server vs. the bundled offline GGUF.

`get_backend()` is the single seam `llm_client.complete()` calls through, so
everything downstream of it (generate_sql, generate_sql_with_retry,
repair_sql, get_relevant_tables, generate_summary) swaps backend for free.
The choice is made by `app_config.LLM_BACKEND` — "ollama" during
development (fast to iterate: swap models with `ollama pull`, no multi-GB
file to manage) or "local" for the packaged build (loads models/*.gguf via
llama-cpp-python, no server process, no network). See README.md for the
exact model file this ships with and how to obtain it.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Protocol

OLLAMA_URL = "http://localhost:11434/api/generate"

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

# Must match the file documented in README.md's "Local model" section — that
# is the one place the exact source/filename is pinned for reproducibility.
DEFAULT_LOCAL_MODEL_FILENAME = "qwen2.5-coder-7b-instruct-q4_k_m.gguf"


class BackendError(RuntimeError):
    """Backend-agnostic failure. llm_client.complete() wraps this as LLMError
    so callers do not need to know which backend is active."""


class LLMBackend(Protocol):
    def generate(self, prompt: str, temperature: float = 0.0, timeout: int = 300) -> str: ...


class OllamaBackend:
    """Thin wrapper around the Ollama HTTP API. This is last phase's client
    logic, moved here unchanged so both backends sit behind one interface."""

    def __init__(self, model: str, url: str = OLLAMA_URL):
        self.model = model
        self.url = url

    def generate(self, prompt: str, temperature: float = 0.0, timeout: int = 300) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise BackendError(
                f"Ollama did not respond within {timeout}s. A large schema on a 7B "
                f"model is slow on first call while weights load; retry, or trim the "
                f"schema passed as context."
            ) from exc
        except urllib.error.URLError as exc:
            raise BackendError(
                f"Could not reach Ollama at {self.url} ({exc}). Is `ollama serve` running?"
            ) from exc
        except json.JSONDecodeError as exc:
            raise BackendError(f"Ollama returned malformed JSON: {exc}") from exc

        if "error" in body:
            raise BackendError(f"Ollama error: {body['error']}")
        return body.get("response", "")


class LocalGGUFBackend:
    """Loads the bundled GGUF file via llama-cpp-python and generates locally.

    Fully offline once loaded: llama-cpp-python runs the model in-process with
    no HTTP client and no server, so there is nothing left that could make a
    network call during inference (see README.md's offline-confirmation note).

    The weight file is large enough (~4-5GB) that loading it takes several
    seconds, so loading is lazy and cached on the instance rather than done in
    __init__ — `preload()` exists so the UI can trigger that wait up front,
    behind a "Loading model..." message, instead of stalling the first
    question the user asks.
    """

    def __init__(self, model_path: Optional[Path] = None, n_ctx: int = 8192):
        self.model_path = Path(model_path) if model_path else MODELS_DIR / DEFAULT_LOCAL_MODEL_FILENAME
        self.n_ctx = n_ctx
        self._llm = None

    def _ensure_loaded(self) -> None:
        if self._llm is not None:
            return
        if not self.model_path.exists():
            raise BackendError(
                f"Local model not found at {self.model_path}. Download the GGUF "
                f"file documented in README.md under 'Local model' and place it "
                f"in models/."
            )
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise BackendError(
                "llama-cpp-python is not installed. Run `pip install -r "
                "requirements.txt`."
            ) from exc

        import multiprocessing

        # llama-cpp-python's own default is cpu_count() // 2, tuned for a
        # machine also doing other work. This app has nothing else CPU-bound
        # running during a generate() call, so all cores is the right default.
        threads = multiprocessing.cpu_count()
        self._llm = Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_threads=threads,
            n_threads_batch=threads,
            verbose=False,
        )

    def preload(self) -> None:
        """Force the load now. Called once at app startup when LLM_BACKEND=local."""
        self._ensure_loaded()

    def generate(self, prompt: str, temperature: float = 0.0, timeout: int = 300) -> str:
        # timeout is accepted for interface parity with OllamaBackend; a local
        # in-process call has no network leg to time out on.
        #
        # Goes through create_chat_completion, not the raw completion API.
        # OllamaBackend's /api/generate call applies the model's chat template
        # server-side unless told not to (`raw: true`, which this code never
        # sets) -- so Ollama has been running every one of these prompts as one
        # ChatML user turn, and the instruct-tuned model replies with its real
        # EOS token (<|im_end|>) at the end of the answer. Feeding the same
        # prompt to the raw completion API skips that wrapping: the model never
        # sees a turn boundary, has no reliable stop signal, and runs on for
        # hundreds of tokens restating the pattern instead of stopping after
        # the SQL statement. Wrapping the prompt as a single user message here
        # is what makes local output match Ollama's instead of rambling to
        # max_tokens on every call.
        self._ensure_loaded()
        try:
            result = self._llm.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=1024,
            )
        except Exception as exc:
            raise BackendError(f"Local model failed to generate: {exc}") from exc
        return result["choices"][0]["message"]["content"]


# One Llama instance per process: reloading a multi-GB GGUF per call would
# undo the entire point of preloading it once at startup.
_local_backend: Optional[LocalGGUFBackend] = None


def _get_local_backend() -> LocalGGUFBackend:
    global _local_backend
    if _local_backend is None:
        _local_backend = LocalGGUFBackend()
    return _local_backend


def get_backend(model: str, url: str = OLLAMA_URL) -> LLMBackend:
    """Resolve which backend is active. `model`/`url` only matter for Ollama —
    the local backend always loads the one bundled GGUF."""
    from .app_config import LLM_BACKEND

    if LLM_BACKEND == "local":
        return _get_local_backend()
    return OllamaBackend(model=model, url=url)


def preload_local_backend() -> None:
    """Entry point for the UI's startup loading indicator (see ui/workers.py's
    ModelLoadWorker). A no-op cost-wise when LLM_BACKEND=ollama since nothing
    calls it in that case."""
    _get_local_backend().preload()
