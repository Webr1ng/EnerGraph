"""result_models — EnerGraph Eval 用例、结果、指标、门禁与清单契约

所属层：tests
依赖：pydantic
对接算法层：N/A
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCHEMA_VERSION = "0.1"
EvalMode = Literal["fast", "standard", "production"]


class EvalInput(BaseModel):
    """单个评测案例的用户输入与隔离标识。"""

    user_message: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


class EvalTurn(BaseModel):
    """多轮案例中的单轮消息。"""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class EvalExpected(BaseModel):
    """案例的可评分期望，不包含具体执行实现。"""

    intents: List[str] = Field(default_factory=list)
    agent: Optional[str] = None
    skill: Optional[str] = None
    required_tools: List[str] = Field(default_factory=list)
    forbidden_tools: List[str] = Field(default_factory=list)
    optional_tools: List[str] = Field(default_factory=list)
    tool_arguments: Dict[str, Any] = Field(default_factory=dict)
    tool_call_counts: Dict[str, int] = Field(default_factory=dict)
    tool_order: List[str] = Field(default_factory=list)
    answer_contains: List[str] = Field(default_factory=list)
    answer_forbidden: List[str] = Field(default_factory=list)
    should_reject: bool = False
    memory_should_write: Optional[bool] = None
    expected_memory_type: Optional[str] = None
    expected_memory_key: Optional[str] = None
    expected_retrieved_aliases: List[str] = Field(default_factory=list)
    expected_latest_content: Optional[str] = None

    @model_validator(mode="after")
    def validate_tool_sets(self) -> "EvalExpected":
        """保证 required、forbidden、optional 工具集合互不冲突。"""
        groups = {
            "required_tools": set(self.required_tools),
            "forbidden_tools": set(self.forbidden_tools),
            "optional_tools": set(self.optional_tools),
        }
        names = list(groups)
        for index, left in enumerate(names):
            for right in names[index + 1:]:
                overlap = groups[left] & groups[right]
                if overlap:
                    raise ValueError(f"{left} 与 {right} 存在重复工具: {sorted(overlap)}")
        return self


class EvalCase(BaseModel):
    """版本化 JSONL 评测用例。"""

    model_config = ConfigDict(extra="allow")

    case_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}$")
    version: Literal[SCHEMA_VERSION]
    category: str = Field(min_length=1)
    tags: List[str] = Field(min_length=1)
    input: EvalInput
    fixtures: Dict[str, Any] = Field(default_factory=dict)
    expected: EvalExpected
    turns: List[EvalTurn] = Field(default_factory=list)


class MetricResult(BaseModel):
    """单项质量指标结果，score 统一归一化到 0～1。"""

    name: str = Field(min_length=1)
    score: float = Field(ge=0, le=1)
    threshold: Optional[float] = Field(default=None, ge=0, le=1)
    passed: Optional[bool] = None
    evidence_summary: Optional[str] = None


class GateResult(BaseModel):
    """零容忍门禁结果；violated 为真表示整次运行失败。"""

    name: str = Field(min_length=1)
    violated: bool
    evidence_summary: Optional[str] = None


class ToolCallRecord(BaseModel):
    """脱敏后的 Tool 调用证据。"""

    name: str = Field(min_length=1)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result_summary: Optional[str] = None
    error: Optional[str] = None


class EvalResult(BaseModel):
    """单案例执行、评分和证据结果。"""

    run_id: str = Field(min_length=1)
    case_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}$")
    mode: EvalMode
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    code_version: str = Field(min_length=1)
    actual_intents: List[str] = Field(default_factory=list)
    actual_agent: Optional[str] = None
    actual_skill: Optional[str] = None
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    answer: str = ""
    protocol_events: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: List[MetricResult] = Field(default_factory=list)
    gates: List[GateResult] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    error: Optional[str] = None
    evidence_summary: Optional[str] = None
    observations: Dict[str, Any] = Field(default_factory=dict)

    @property
    def hard_gate_passed(self) -> bool:
        """返回所有零容忍门禁是否均未触发。"""
        return not any(gate.violated for gate in self.gates)


class RunManifest(BaseModel):
    """一次可复现评测运行的环境与版本清单。"""

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    mode: EvalMode
    git_commit: str = Field(min_length=1)
    git_dirty: bool
    dataset_versions: Dict[str, str] = Field(min_length=1)
    threshold_version: str = Field(min_length=1)
    config_summary: Dict[str, Any] = Field(default_factory=dict)
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    started_at: datetime
    finished_at: Optional[datetime] = None
    random_seed: int
    environment: Dict[str, str] = Field(default_factory=dict)
