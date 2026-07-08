"""test_llm_config — 验证统一 LLM 工厂的本地 vLLM 参数适配

所属层：tests
依赖：pytest, unittest.mock, src.config.llm
对接算法层：N/A
"""
from unittest.mock import patch

from src.config.llm import get_llm


def test_local_qwen_thinking_flag_uses_vllm_extra_body(monkeypatch) -> None:
    """Qwen 关闭思考参数应放入 vLLM extra_body，不能成为 SDK 顶层参数。"""
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_MODEL", "qwen3.6-35b-a3b")
    monkeypatch.setenv("LOCAL_BASE_URL", "http://192.0.2.1:8001/v1")
    monkeypatch.delenv("LOCAL_EXTRA_KWARGS", raising=False)

    with patch("langchain_openai.ChatOpenAI") as chat_openai:
        get_llm(temperature=0, streaming=False)

    kwargs = chat_openai.call_args.kwargs
    assert kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }
    assert "model_kwargs" not in kwargs
