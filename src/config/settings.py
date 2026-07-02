"""settings — 统一配置加载

所属层：config
依赖：pydantic, pyyaml, python-dotenv
对接算法层：N/A
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

# 加载 .env 文件
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)


class ModelConfig(BaseModel):
    """模型配置"""
    provider: str = Field(default="openai", description="LLM 提供商")
    name: str = Field(default="gpt-4", description="模型名称")
    temperature: float = Field(default=0.7, ge=0, le=2, description="温度参数")
    max_tokens: int = Field(default=2000, gt=0, description="最大输出 token 数")


class AgentConfig(BaseModel):
    """Agent 行为配置"""
    max_iterations: int = Field(default=10, ge=1, le=50, description="最大迭代次数")
    timeout: int = Field(default=60, gt=0, description="超时时间 (秒)")


class ToolDef(BaseModel):
    """工具定义"""
    name: str
    description: str


class RAGConfig(BaseModel):
    """RAG 检索配置"""
    top_k: int = Field(default=3, ge=1, le=20, description="检索返回条数")
    confidence_threshold: float = Field(default=0.6, ge=0, le=2, description="置信度阈值，top-1 distance 超过此值标记 low_confidence")
    dedup_similarity: float = Field(default=0.98, ge=0, le=1, description="去重相似度阈值，cosine_sim 超过此值的重复片段被剔除")


class OutputConfig(BaseModel):
    """输出配置"""
    language: str = Field(default="zh", description="输出语言")
    format: str = Field(default="markdown", description="输出格式")


class ApiConfig(BaseModel):
    """API 服务配置"""
    host: str = Field(default="0.0.0.0", description="服务监听地址")
    port: int = Field(default=8000, ge=1, le=65535, description="服务端口")
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], description="CORS 允许的源列表")
    api_key: str = Field(default="", description="API 鉴权密钥，空字符串表示不启用鉴权")


class MemoryConfig(BaseModel):
    """记忆模块配置"""
    enabled: bool = Field(default=False, description="是否启用持久化记忆")
    postgres_dsn: str = Field(
        default="postgresql://energraph:energraph@localhost:5432/energraph",
        description="L1 checkpoint 与 L2 store 共用 PostgreSQL DSN",
    )
    checkpoint_table: str = Field(default="checkpoints", description="checkpoint 表名前缀")
    store_table: str = Field(default="store", description="长期记忆 store 表名前缀")
    namespace_prefix: str = Field(default="energraph", description="长期记忆 namespace 全局前缀")
    env: str = Field(default="dev", description="记忆隔离环境：dev/staging/prod")
    default_site_id: str = Field(default="local", description="缺省站点 ID")
    default_agent_id: str = Field(default="main_graph", description="缺省 Agent ID")
    default_ttl_seconds: int = Field(default=0, ge=0, description="缺省 TTL，0 表示长期有效")
    auto_extract_enabled: bool = Field(default=False, description="是否启用 LLM 结构化长期记忆抽取")
    extract_min_confidence: float = Field(default=0.65, ge=0, le=1, description="自动抽取写入最低置信度")
    max_memories_per_turn: int = Field(default=3, ge=1, le=10, description="单轮自动写入记忆上限")
    device_state_default_ttl_seconds: int = Field(
        default=86400,
        ge=1,
        description="设备状态类临时记忆默认 TTL",
    )
    strict_msgpack: bool = Field(default=True, description="是否启用 LangGraph 安全反序列化")
    use_postgres_store: bool = Field(default=False, description="L2 是否尝试使用 PostgresStore")
    postgres_pool_min_size: int = Field(default=1, ge=1, description="L2 PostgresStore 连接池最小连接数")
    postgres_pool_max_size: int = Field(default=10, ge=1, description="L2 PostgresStore 连接池最大连接数")
    postgres_setup_enabled: bool = Field(default=True, description="启动时是否执行 L2 PostgresStore.setup()")
    demo_file_store_enabled: bool = Field(default=False, description="是否启用 demo 文件长期记忆落盘")
    demo_file_store_path: str = Field(
        default="data/long_term_memory_demo/memories.json",
        description="demo 文件长期记忆路径，仅供本地人工测试",
    )


class AppConfig(BaseModel):
    """应用顶层配置"""
    model: ModelConfig = Field(default_factory=ModelConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    tools: List[ToolDef] = Field(default_factory=list)
    output: OutputConfig = Field(default_factory=OutputConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    prompts: Dict[str, Any] = Field(default_factory=dict)
    routes: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)


def _load_prompts() -> Dict[str, Any]:
    """加载 prompts/ 目录下的多文件 Prompt 配置。"""
    prompts_dir = _PROJECT_ROOT / "src" / "config" / "prompts"
    prompts = {}

    if not prompts_dir.exists() or not prompts_dir.is_dir():
        print(f"[WARNING] Prompts 配置目录不存在: {prompts_dir}")
        return {}

    for yaml_file in sorted(prompts_dir.glob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f) or {}
                prompts.update(content)
        except (yaml.YAMLError, OSError) as e:
            print(f"[WARNING] 无法加载 Prompt 文件 {yaml_file.name}: {e}")

    # 注入共享片段（_shared.yaml）
    shared = prompts.get("_shared", {})
    if shared:
        principles = shared.get("answer_principles", "")
        jump_rules = shared.get("jump_rules", "")
        for key in list(prompts.keys()):
            if key == "_shared" or not isinstance(prompts[key], dict):
                continue
            system = prompts[key].get("system", "")
            if principles and "## 回答原则" not in system:
                system += f"\n\n## 回答原则\n{principles}"
            if jump_rules and "## 页面跳转说明" not in system:
                system += f"\n\n## 页面跳转说明\n{jump_rules}"
            prompts[key]["system"] = system

    return prompts


def _load_routes() -> Dict[str, Any]:
    """加载路由注册表配置"""
    routes_path = _PROJECT_ROOT / "config" / "routes.yaml"
    if not routes_path.exists():
        print(f"[WARNING] 路由配置文件不存在: {routes_path}")
        return {}

    try:
        with open(routes_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        print(f"[WARNING] 无法加载路由文件: {e}")
        return {}


def _load_yaml_config(yaml_path: Optional[Path] = None) -> Dict[str, Any]:
    """加载 YAML 配置文件"""
    if yaml_path is None:
        yaml_path = _PROJECT_ROOT / "config" / "agent_config.yaml"

    if not yaml_path.exists():
        return {}

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        print(f"[WARNING] 无法加载配置文件 {yaml_path}: {e}")
        return {}


def _apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """用环境变量覆盖 YAML 配置"""
    env_map = {
        "LLM_PROVIDER": ("model", "provider"),
        "OPENAI_API_KEY": ("api_key", None),
        "OPENAI_MODEL": ("model", "name"),
        "OPENAI_BASE_URL": ("model", "base_url"),
        "ANTHROPIC_API_KEY": ("api_key", None),
        "ANTHROPIC_MODEL": ("model", "name"),
        "DEEPSEEK_API_KEY": ("api_key", None),
        "DEEPSEEK_MODEL": ("model", "name"),
        "AGENT_TEMPERATURE": ("model", "temperature"),
        "AGENT_MAX_ITERATIONS": ("agent", "max_iterations"),
        "LOG_LEVEL": ("log_level", None),
        "API_HOST": ("api", "host"),
        "API_PORT": ("api", "port"),
        "API_KEY": ("api", "api_key"),
        "MEMORY_ENABLED": ("memory", "enabled"),
        "MEMORY_POSTGRES_DSN": ("memory", "postgres_dsn"),
        "CHECKPOINT_TABLE": ("memory", "checkpoint_table"),
        "STORE_TABLE": ("memory", "store_table"),
        "MEMORY_NAMESPACE_PREFIX": ("memory", "namespace_prefix"),
        "MEMORY_ENV": ("memory", "env"),
        "MEMORY_DEFAULT_SITE_ID": ("memory", "default_site_id"),
        "MEMORY_DEFAULT_AGENT_ID": ("memory", "default_agent_id"),
        "MEMORY_DEFAULT_TTL_SECONDS": ("memory", "default_ttl_seconds"),
        "MEMORY_AUTO_EXTRACT_ENABLED": ("memory", "auto_extract_enabled"),
        "MEMORY_EXTRACT_MIN_CONFIDENCE": ("memory", "extract_min_confidence"),
        "MEMORY_MAX_MEMORIES_PER_TURN": ("memory", "max_memories_per_turn"),
        "MEMORY_DEVICE_STATE_DEFAULT_TTL_SECONDS": ("memory", "device_state_default_ttl_seconds"),
        "LANGGRAPH_STRICT_MSGPACK": ("memory", "strict_msgpack"),
        "MEMORY_USE_POSTGRES_STORE": ("memory", "use_postgres_store"),
        "MEMORY_POSTGRES_POOL_MIN_SIZE": ("memory", "postgres_pool_min_size"),
        "MEMORY_POSTGRES_POOL_MAX_SIZE": ("memory", "postgres_pool_max_size"),
        "MEMORY_POSTGRES_SETUP_ENABLED": ("memory", "postgres_setup_enabled"),
        "MEMORY_DEMO_FILE_STORE_ENABLED": ("memory", "demo_file_store_enabled"),
        "MEMORY_DEMO_FILE_STORE_PATH": ("memory", "demo_file_store_path"),
    }

    for env_var, (section, key) in env_map.items():
        value = os.getenv(env_var)
        if value is None:
            continue
        if key is None:
            config[section] = value
        else:
            config.setdefault(section, {})[key] = value
            # 环境变量类型转换
            if value.isdigit():
                config[section][key] = int(value)
            elif value.replace(".", "", 1).isdigit():
                config[section][key] = float(value)
            elif value.lower() in ("true", "false"):
                config[section][key] = value.lower() == "true"

    # API_CORS_ORIGINS: 逗号分隔的列表
    cors_origins = os.getenv("API_CORS_ORIGINS")
    if cors_origins is not None:
        config.setdefault("api", {})["cors_origins"] = [
            o.strip() for o in cors_origins.split(",") if o.strip()
        ]

    return config


def create_settings(yaml_path: Optional[Path] = None) -> AppConfig:
    """创建应用配置实例

    加载顺序: YAML 文件 → 环境变量覆盖 → Pydantic 验证 → Prompts & Routes
    """
    raw = _load_yaml_config(yaml_path)
    raw = _apply_env_overrides(raw)

    # 加载 prompts 和 routes
    raw["prompts"] = _load_prompts()
    raw["routes"] = _load_routes()

    return AppConfig(**raw)


# 全局单例
settings = create_settings()
