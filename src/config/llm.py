"""llm — 统一 LLM 实例工厂（按 LLM_PROVIDER 切换供应商）

所属层：config
依赖：langchain_openai, langchain_anthropic, src.config.settings
对接算法层：N/A
"""
import os
from typing import Any

from src.config.settings import settings


def get_llm(temperature: float | None = None, streaming: bool = True) -> Any:
    """创建 LLM 实例，按 LLM_PROVIDER 选择供应商。

    统一入口：主图节点 / 记忆抽取 / 意图解析均调用本函数，切换供应商只改 .env
    的 LLM_PROVIDER 一处即全局生效。DeepSeek 与 ModelScope 均禁用 thinking
    （extra_body={"thinking":{"type":"disabled"}}），避免 tool calling 时
    reasoning_content 字段报错。

    Args:
        temperature: 温度；None 用 settings.model.temperature
        streaming: 是否流式输出

    Returns:
        ChatOpenAI / ChatAnthropic 实例
    """
    provider = os.getenv("LLM_PROVIDER", settings.model.provider).lower()
    if temperature is None:
        temperature = settings.model.temperature

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.model.name,
            temperature=temperature,
            base_url="https://api.deepseek.com/v1",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            streaming=streaming,
            extra_body={"thinking": {"type": "disabled"}},
        )
    if provider == "modelscope":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=os.getenv("MODELSCOPE_MODEL", "deepseek-ai/DeepSeek-V4-Flash"),
            temperature=temperature,
            base_url=os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1"),
            api_key=os.getenv("MODELSCOPE_API_KEY"),
            streaming=streaming,
            extra_body={"thinking": {"type": "disabled"}},
        )
    if provider == "local":
        from langchain_openai import ChatOpenAI

        model = os.getenv("LOCAL_MODEL", "qwen3.6-27b")
        # Qwen3 系列需要显式关闭思考模式；Qwen2.5 / 其他模型无需此参数
        extra_kwargs: dict = {}
        if model.lower().startswith("qwen3"):
            extra_kwargs["model_kwargs"] = {
                "chat_template_kwargs": {"enable_thinking": False}
            }

        return ChatOpenAI(
            model=model,
            temperature=temperature,
            base_url=os.getenv("LOCAL_BASE_URL", "http://localhost:8001/v1"),
            api_key=os.getenv("LOCAL_API_KEY", "not-needed"),
            streaming=streaming,
            **extra_kwargs,
        )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.model.name, temperature=temperature, streaming=streaming)

    # openai 及其他兼容 OpenAI 的网关（靠 OPENAI_API_KEY / OPENAI_BASE_URL 环境变量）
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=settings.model.name, temperature=temperature, streaming=streaming)
