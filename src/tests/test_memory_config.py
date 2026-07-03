"""test_memory_config — 验证记忆模块 PostgreSQL 配置安全边界

所属层：tests
依赖：pytest, pydantic, src.config.settings
对接算法层：N/A
"""
import pytest
from pydantic import ValidationError

from src.config.settings import MemoryConfig


def test_disabled_memory_allows_empty_postgres_dsn() -> None:
    """未启用 PostgreSQL 记忆时允许 DSN 为空。"""
    config = MemoryConfig()

    assert config.postgres_dsn == ""


@pytest.mark.parametrize(
    ("overrides"),
    [
        {"enabled": True},
        {"use_postgres_store": True},
    ],
)
def test_postgres_memory_requires_explicit_dsn(overrides: dict) -> None:
    """L1 或 L2 PostgreSQL 启用时必须显式配置 DSN。"""
    with pytest.raises(ValidationError, match="MEMORY_POSTGRES_DSN"):
        MemoryConfig(**overrides)


def test_development_allows_explicit_local_postgres() -> None:
    """开发环境允许显式连接本机 PostgreSQL。"""
    config = MemoryConfig(
        enabled=True,
        use_postgres_store=True,
        postgres_dsn="postgresql://energraph:energraph@localhost:5432/energraph",
        env="dev",
    )

    assert config.postgres_dsn.endswith("/energraph")


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://<username>:<password>@<host>:5432/<database>",
        "postgresql://user:***@postgres:5432/energraph",
        "not-a-postgres-dsn",
    ],
)
def test_enabled_memory_rejects_placeholder_or_invalid_dsn(dsn: str) -> None:
    """启用记忆时拒绝占位符和无效连接串。"""
    with pytest.raises(ValidationError):
        MemoryConfig(enabled=True, postgres_dsn=dsn)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://app:strong-secret@localhost:5432/energraph",
        "postgresql://app:energraph@postgres:5432/energraph",
    ],
)
def test_production_rejects_localhost_and_example_password(dsn: str) -> None:
    """生产环境拒绝本机地址和示例密码。"""
    with pytest.raises(ValidationError):
        MemoryConfig(enabled=True, postgres_dsn=dsn, env="prod")


def test_production_accepts_injected_postgres_dsn() -> None:
    """生产环境接受注入的非示例 PostgreSQL 配置。"""
    config = MemoryConfig(
        enabled=True,
        use_postgres_store=True,
        postgres_dsn="postgresql://energraph_app:strong-secret@postgres:5432/energraph",
        env="prod",
    )

    assert config.env == "prod"
