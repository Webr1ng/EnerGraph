"""extractor — L2 长期记忆结构化抽取器

所属层：memory
依赖：json, langchain_core, src.config.settings, src.schemas.memory
对接算法层：N/A
"""
import json
import os
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from src.config.settings import settings
from src.schemas.memory import MemoryExtractionResult


def _get_extraction_llm() -> Any:
    """创建记忆抽取 LLM 实例（统一走 src.config.llm.get_llm）。

    Returns:
        可调用 invoke(messages) 的 ChatModel 实例。
    """
    from src.config.llm import get_llm

    return get_llm(temperature=0, streaming=False)


def _strip_json_fence(text: str) -> str:
    """移除 LLM 可能返回的 Markdown JSON 代码块包裹。

    Args:
        text: LLM 原始输出。

    Returns:
        可供 json.loads 解析的字符串。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _dump_turn_payload(
    user_input: str,
    final_report: str,
    agent_id: str,
    site_id: str,
    thread_id: str,
) -> str:
    """构建记忆抽取的本轮上下文 JSON。

    Args:
        user_input: 本轮用户输入。
        final_report: 本轮助手最终回答。
        agent_id: 当前 Agent ID。
        site_id: 当前站点 ID。
        thread_id: 当前会话 ID。

    Returns:
        JSON 字符串。
    """
    payload: Dict[str, Any] = {
        "user_input": user_input,
        "assistant_final_report": final_report,
        "context": {
            "agent_id": agent_id,
            "site_id": site_id,
            "thread_id": thread_id,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_memory_extraction_response(raw_content: str) -> MemoryExtractionResult:
    """解析 LLM 结构化抽取输出。

    Args:
        raw_content: LLM 返回的 JSON 文本。

    Returns:
        MemoryExtractionResult 实例。

    Raises:
        ValueError: 返回内容不是合法 JSON 或不符合模型结构。
    """
    try:
        payload = json.loads(_strip_json_fence(raw_content))
    except json.JSONDecodeError as exc:
        raise ValueError(f"memory extraction returned invalid JSON: {exc}") from exc
    return MemoryExtractionResult(**payload)


def extract_memories_from_turn(
    user_input: str,
    final_report: str,
    agent_id: str,
    site_id: str,
    thread_id: str,
    prompt: str,
    llm: Optional[Any] = None,
) -> MemoryExtractionResult:
    """从单轮对话中抽取长期记忆候选。

    Args:
        user_input: 本轮用户输入。
        final_report: 本轮助手最终回答。
        agent_id: 当前 Agent ID。
        site_id: 当前站点 ID。
        thread_id: 当前会话 ID。
        prompt: 从 prompts 配置加载的系统抽取 Prompt。
        llm: 可选 fake/自定义 LLM，用于测试。

    Returns:
        结构化记忆抽取结果。

    Raises:
        ValueError: LLM 输出无法解析时抛出。
        Exception: 底层 LLM 调用失败时透传给调用方处理。
    """
    model = llm or _get_extraction_llm()
    response = model.invoke(
        [
            SystemMessage(content=prompt),
            HumanMessage(
                content=_dump_turn_payload(
                    user_input=user_input,
                    final_report=final_report,
                    agent_id=agent_id,
                    site_id=site_id,
                    thread_id=thread_id,
                )
            ),
        ]
    )
    return parse_memory_extraction_response(str(response.content))
