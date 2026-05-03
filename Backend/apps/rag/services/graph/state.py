"""
LangGraph State Definition
All agents read/write to this shared state object.
"""
from typing import Annotated, Any, Dict, List, Optional, TypedDict
from langgraph.graph.message import add_messages


class RAGState(TypedDict):
    """
    Shared state flowing through the LangGraph pipeline.
    Every node reads from and writes to this dict.
    """
    # Core
    query: str
    session_id: Optional[str]
    document_id: Optional[str]
    document_filter: Optional[str]
    top_k: int
    strategy: str

    # Planning
    query_type: str          # factual / analytical / search_query / etc.
    complexity: str          # simple / medium / complex
    requires_internet: bool
    parallel_execution: bool

    # Retrieval
    retrieved_chunks: List[Dict[str, Any]]
    retrieval_scores: List[float]

    # Search
    internet_sources: List[Dict[str, Any]]
    tavily_answer: Optional[str]

    # RL Decision
    rl_action: str           # RETRIEVE_MORE / RE_RANK / ANSWER_NOW
    rl_step_count: int
    rl_confidence: float
    rl_metadata: Dict[str, Any]

    # Answer
    final_answer: str
    answer_confidence: float

    # Evaluation
    evaluation_result: Dict[str, Any]  # factuality, coverage, hallucination_risk

    # Execution trace (for debugging)
    execution_trace: List[Dict[str, Any]]

    # Error handling
    error: Optional[str]