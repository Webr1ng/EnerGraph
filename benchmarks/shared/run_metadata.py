"""run_metadata — 构建可追溯且不含凭据的 Eval 运行清单

所属层：tests
依赖：git, platform, benchmarks.shared
对接算法层：N/A
"""
import platform
import subprocess
from hashlib import sha1
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from benchmarks.shared.config_models import EvalRunConfig, config_summary
from benchmarks.shared.result_models import RunManifest


def _git_output(args: list[str], cwd: Path) -> str:
    """执行只读 Git 命令并返回文本，失败时返回 unknown。"""
    try:
        return subprocess.check_output(
            ["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _build_prompt_version(commit: str, status: str, root: Path) -> str:
    """构建可区分未提交 Prompt/Harness 变更的版本标识。"""
    version = f"git:{commit[:12]}"
    if status in {"", "unknown"}:
        return version
    diff = _git_output(
        ["diff", "--", "src/config/prompts", "benchmarks", "src/graph", "src/tools"],
        root,
    )
    if diff not in {"", "unknown"}:
        return f"{version}+dirty:{sha1(diff.encode('utf-8')).hexdigest()[:8]}"
    return f"{version}+dirty"


def build_run_manifest(
    *,
    run_id: str,
    config: EvalRunConfig,
    dataset_versions: Dict[str, str],
    model_id: str,
    threshold_version: str = "0.1",
    project_root: Optional[Path] = None,
    started_at: Optional[datetime] = None,
) -> RunManifest:
    """从 Git、配置和运行环境构建 Manifest。

    Args:
        run_id: 本次运行标识。
        config: 已验证运行配置。
        dataset_versions: 模块到数据集版本的映射。
        model_id: 实际模型或固定 Fixture 标识。
        threshold_version: 阈值版本。
        project_root: Git 项目根目录。
        started_at: 可注入的开始时间，便于确定性测试。

    Returns:
        不含密钥、Token 或 DSN 的 RunManifest。
    """
    root = project_root or Path(__file__).resolve().parents[2]
    commit = _git_output(["rev-parse", "HEAD"], root)
    status = _git_output(["status", "--porcelain"], root)
    prompt_version = _build_prompt_version(commit, status, root)
    return RunManifest(
        run_id=run_id,
        mode=config.mode,
        git_commit=commit,
        git_dirty=status not in {"", "unknown"},
        dataset_versions=dataset_versions,
        threshold_version=threshold_version,
        config_summary=config_summary(config),
        model_id=model_id,
        prompt_version=prompt_version,
        started_at=started_at or datetime.now(timezone.utc),
        random_seed=config.options.random_seed,
        environment={
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    )
