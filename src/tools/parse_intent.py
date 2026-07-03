"""parse_intent — 业务意图解析工具，将自然语言转化为 ConstraintMatrix

所属层：tools
依赖：langchain_core, src.schemas.v3_engine, src.config.settings
对接算法层：N/A（纯 LLM 调用）
"""
import json
import logging
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from src.schemas.v3_engine import ConstraintMatrix
from src.config.settings import settings

logger = logging.getLogger(__name__)


def _get_system_prompt() -> str:
    """从 settings.prompts 加载 parse_intent system prompt（支持多文件）"""
    prompts = settings.prompts or {}
    return prompts.get("parse_intent", {}).get("system", "")


def parse_business_intent(user_input: str) -> Dict[str, Any]:
    """将自然语言或 ERP/MES 输入转化为底层 DFL 可读的约束矩阵。

    Args:
        user_input: 用户自然语言输入，如"明天有大批订单急产"

    Returns:
        ConstraintMatrix 的 dict 表示
    """
    try:
        from src.config.llm import get_llm

        llm = get_llm(temperature=0, streaming=False)

        response = llm.invoke([
            SystemMessage(content=_get_system_prompt()),
            HumanMessage(content=user_input),
        ])
        data = json.loads(response.content)
        return ConstraintMatrix(**data).model_dump()
    except Exception as e:
        logger.error(f"parse_business_intent 失败: {e}")
        return {"error": f"parse_business_intent: {e}"}
