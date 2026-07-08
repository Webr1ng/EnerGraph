"""config_models — EnerGraph Eval 分层运行配置契约与启动前检查

所属层：tests
依赖：pydantic, pyyaml
对接算法层：N/A
"""
import os
from pathlib import Path
from typing import Dict, List, Literal, Mapping, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

from benchmarks.shared.result_models import EvalMode, SCHEMA_VERSION


class BackendConfig(BaseModel):
    """单类外部依赖的运行后端。"""

    kind: Literal["mock", "inmemory", "postgres", "real"]


class RunOptions(BaseModel):
    """Adapter 通用超时、重试、随机种子、并发和隔离配置。"""

    timeout_seconds: float = Field(default=30, gt=0)
    retries: int = Field(default=0, ge=0, le=5)
    random_seed: int = 42
    concurrency: int = Field(default=1, ge=1, le=100)
    namespace_prefix: str = Field(default="eval", min_length=1)


class EvalRunConfig(BaseModel):
    """Fast、Standard 或 Production 的完整运行配置。"""

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    mode: EvalMode
    network_allowed: bool
    store: BackendConfig
    llm: BackendConfig
    tools: BackendConfig
    options: RunOptions = Field(default_factory=RunOptions)
    fixture_path: Optional[str] = None
    required_env: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode_boundaries(self) -> "EvalRunConfig":
        """阻止 Fast 访问外部依赖，并阻止 Production 静默使用 Mock。"""
        if self.mode == "fast":
            if self.network_allowed:
                raise ValueError("Fast 模式禁止网络访问")
            if self.store.kind != "inmemory" or self.llm.kind != "mock" or self.tools.kind != "mock":
                raise ValueError("Fast 模式必须使用 InMemory Store、Mock LLM 和 Mock Tools")
        if self.mode == "production":
            if not self.network_allowed:
                raise ValueError("Production 模式必须显式允许真实依赖访问")
            if (self.store.kind, self.llm.kind, self.tools.kind) != ("postgres", "real", "real"):
                raise ValueError("Production 模式必须使用 PostgreSQL、真实 LLM 和真实 Tools")
        return self


def load_run_config(
    path: Path | str,
    *,
    environment: Optional[Mapping[str, str]] = None,
    validate_dependencies: bool = True,
) -> EvalRunConfig:
    """加载运行配置，并在 Production 启动前检查依赖环境变量。

    Args:
        path: YAML 配置路径。
        environment: 用于检查的环境变量映射，默认使用当前进程环境。
        validate_dependencies: 是否执行 required_env 检查。

    Returns:
        已完成模式边界和依赖检查的运行配置。

    Raises:
        ValueError: YAML 根节点非法或 Production 缺少必需配置。
        OSError: 配置文件不可读取。
    """
    resolved = Path(path)
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{resolved}: 配置根节点必须是对象")
    config = EvalRunConfig.model_validate(payload)
    if validate_dependencies and config.required_env:
        env = environment if environment is not None else os.environ
        missing = [key for key in config.required_env if not str(env.get(key, "")).strip()]
        if missing:
            label = "Production" if config.mode == "production" else config.mode.title()
            raise ValueError(f"{label} 缺少必需环境变量: {', '.join(sorted(missing))}")
    return config


def config_summary(config: EvalRunConfig) -> Dict[str, object]:
    """生成不含凭据的运行配置摘要。"""
    return {
        "schema_version": config.schema_version,
        "mode": config.mode,
        "network_allowed": config.network_allowed,
        "store": config.store.kind,
        "llm": config.llm.kind,
        "tools": config.tools.kind,
        "options": config.options.model_dump(mode="json"),
    }
