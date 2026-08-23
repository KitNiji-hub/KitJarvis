"""Network-free regression tests for the live performance harness."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from jarvis import llm as llm_module
from jarvis.llm import OllamaBackend, OpenAICompatibleBackend
from tests.performance.timing_recorder import TimingRecorder


def _load_pipeline_timings(monkeypatch):
    """Load the live harness without probing a real Ollama during import."""

    class _UnavailableResponse:
        status_code = 503

    monkeypatch.setattr(
        "requests.get", lambda *args, **kwargs: _UnavailableResponse()
    )
    path = Path(__file__).parent / "performance" / "test_pipeline_timings.py"
    spec = importlib.util.spec_from_file_location(
        "_performance_pipeline_timings_under_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_harness_pins_canonical_and_legacy_ollama_fields(monkeypatch):
    """Ambient eval-judge settings must not redirect the Ollama benchmark."""

    monkeypatch.setenv("EVAL_JUDGE_BASE_URL", "http://localhost:1234")
    monkeypatch.setenv("EVAL_JUDGE_MODEL", "judge-model")
    harness = _load_pipeline_timings(monkeypatch)

    cfg = harness._make_cfg()

    assert cfg.llm_provider == "ollama"
    assert cfg.llm_base_url == harness.OLLAMA_URL
    assert cfg.ollama_base_url == harness.OLLAMA_URL
    assert cfg.llm_chat_model == harness.PERF_MODEL
    assert cfg.ollama_chat_model == harness.PERF_MODEL
    assert cfg.fast_model == harness.PERF_MODEL


@pytest.mark.parametrize("backend_class", [OllamaBackend, OpenAICompatibleBackend])
def test_recorder_captures_object_style_main_chat(monkeypatch, backend_class):
    """Fresh factory-created backend instances must cross the timing seam."""

    def fake_chat(
        self,
        chat_model,
        messages,
        timeout_sec=30.0,
        extra_options=None,
        tools=None,
        thinking=False,
    ):
        return {"message": {"content": "recorded"}}

    monkeypatch.setattr(backend_class, "chat", fake_chat)
    backend = backend_class("http://localhost:11434")

    def run_reply_engine():
        return backend.chat(
            "test-model",
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hello"},
            ],
        )

    with TimingRecorder() as recorder:
        result = run_reply_engine()

    assert result == {"message": {"content": "recorded"}}
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call.context == "main_chat_turn"
    assert call.model == "test-model"
    assert call.prompt_chars == len("systemhello")
    assert call.response_chars == len("recorded")
    assert backend_class.chat is fake_chat


def test_recorder_captures_function_style_direct_once(monkeypatch):
    """Function-style helpers delegate through the same seam without duplicates."""

    def fake_direct(
        self,
        chat_model,
        system_prompt,
        user_content,
        timeout_sec=10.0,
        thinking=False,
        num_ctx=4096,
        temperature=None,
        max_tokens=None,
    ):
        return "OK"

    monkeypatch.setattr(OllamaBackend, "direct", fake_direct)

    with TimingRecorder() as recorder:
        result = llm_module.call_llm_direct(
            "http://localhost:11434",
            "test-model",
            "system",
            "hello",
        )

    assert result == "OK"
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call.model == "test-model"
    assert call.prompt_chars == len("systemhello")
    assert call.response_chars == len("OK")


def test_recorder_classifies_object_style_planner_call(monkeypatch):
    """Planner latency must not be folded into the main-chat bucket."""

    def fake_direct(
        self,
        chat_model,
        system_prompt,
        user_content,
        timeout_sec=10.0,
        thinking=False,
        num_ctx=4096,
        temperature=None,
        max_tokens=None,
    ):
        return "Reply to the user."

    monkeypatch.setattr(OllamaBackend, "direct", fake_direct)
    backend = OllamaBackend("http://localhost:11434")

    def plan_query():
        return backend.direct("test-model", "system", "hello")

    with TimingRecorder() as recorder:
        plan_query()

    assert len(recorder.calls) == 1
    assert recorder.calls[0].context == "planner"


def test_recorder_classifies_object_style_tool_router_call(monkeypatch):
    """The current router helper must have its own timing bucket."""

    def fake_direct(
        self,
        chat_model,
        system_prompt,
        user_content,
        timeout_sec=10.0,
        thinking=False,
        num_ctx=4096,
        temperature=None,
        max_tokens=None,
    ):
        return "none"

    monkeypatch.setattr(OllamaBackend, "direct", fake_direct)
    backend = OllamaBackend("http://localhost:11434")

    def _select_llm():
        return backend.direct("test-model", "system", "hello")

    with TimingRecorder() as recorder:
        _select_llm()

    assert len(recorder.calls) == 1
    assert recorder.calls[0].context == "tool_router"
