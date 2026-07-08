"""loader — 将 10 个 Memory 基础场景扩展为 100 条隔离矩阵记录

所属层：tests
依赖：benchmarks.shared.case_loader
对接算法层：N/A
"""
from pathlib import Path
from typing import List

from benchmarks.shared.case_loader import load_cases
from benchmarks.shared.result_models import EvalCase


_VARIANTS = [
    ("dev", "site_a", "main_graph", "user_a", "thread_a"),
    ("dev", "site_a", "powerai", "user_a", "thread_b"),
    ("dev", "site_b", "hvac_expert", "user_b", "thread_c"),
    ("staging", "site_a", "main_graph", "user_c", "thread_d"),
    ("staging", "site_c", "powerai", "user_d", "thread_e"),
    ("test", "site_d", "ui_router", "user_e", "thread_f"),
    ("test", "site_e", "main_graph", "user_f", "thread_g"),
    ("dev", "site_f", "powerai", "user_g", "thread_h"),
    ("staging", "site_g", "hvac_expert", "user_h", "thread_i"),
    ("test", "site_h", "main_graph", "user_i", "thread_j"),
]


def load_memory_cases(path: Path | str | None = None) -> List[EvalCase]:
    """加载基础场景并展开 env/site/agent/user/thread 隔离矩阵。"""
    source = Path(path) if path else Path(__file__).with_name("base_cases.jsonl")
    base_cases = load_cases(source)
    expanded: List[EvalCase] = []
    for case in base_cases:
        for index, (env, site, agent, user, thread) in enumerate(_VARIANTS, 1):
            clone = case.model_copy(deep=True)
            clone.case_id = f"{case.case_id}_v{index:02d}"
            clone.input.site_id = site
            clone.input.user_id = user
            clone.input.thread_id = thread
            clone.fixtures["memory_context"] = {
                "env": env, "site_id": site, "agent_id": agent,
                "user_id": user, "thread_id": thread,
            }
            expanded.append(clone)
    return expanded

