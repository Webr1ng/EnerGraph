"""adapters — Graph、API、Memory、Tool 与 RAG 评测执行边界。"""

from benchmarks.adapters.api_adapter import ApiAdapter
from benchmarks.adapters.answer_adapter import (
    AnswerAdapter,
    create_answer_fixture_executor,
    create_local_llm_answer_executor,
)
from benchmarks.adapters.faithfulness_adapter import (
    FaithfulnessAdapter,
    create_faithfulness_fixture_executor,
    create_local_llm_faithfulness_executor,
)
from benchmarks.adapters.fault_recovery_adapter import (
    FaultRecoveryAdapter,
    create_fault_recovery_fixture_executor,
    create_fault_recovery_production_executor,
)
from benchmarks.adapters.graph_adapter import (
    GraphAdapter,
    create_energraph_executor,
    create_routing_fixture_executor,
)
from benchmarks.adapters.memory_adapter import (
    MemoryAdapter,
    create_memory_benchmark_executor,
    memory_namespace_cleaner,
)
from benchmarks.adapters.rag_adapter import (
    RagAdapter,
    create_local_rag_executor,
    create_rag_fixture_executor,
)
from benchmarks.adapters.security_adapter import (
    SecurityAdapter,
    create_local_llm_security_executor,
    create_security_fixture_executor,
)
from benchmarks.adapters.tool_adapter import ToolAdapter, create_tool_fixture_executor
from benchmarks.adapters.ui_contract_adapter import (
    UIContractAdapter,
    create_ui_contract_fixture_executor,
)

__all__ = [
    "AnswerAdapter", "ApiAdapter", "FaithfulnessAdapter", "FaultRecoveryAdapter", "GraphAdapter", "MemoryAdapter", "RagAdapter", "SecurityAdapter", "ToolAdapter", "UIContractAdapter",
    "create_answer_fixture_executor", "create_local_llm_answer_executor",
    "create_faithfulness_fixture_executor",
    "create_local_llm_faithfulness_executor",
    "create_fault_recovery_fixture_executor",
    "create_fault_recovery_production_executor",
    "create_local_llm_security_executor", "create_security_fixture_executor",
    "create_energraph_executor",
    "create_routing_fixture_executor",
    "create_rag_fixture_executor",
    "create_local_rag_executor",
    "create_tool_fixture_executor",
    "create_ui_contract_fixture_executor",
    "create_memory_benchmark_executor", "memory_namespace_cleaner",
]
