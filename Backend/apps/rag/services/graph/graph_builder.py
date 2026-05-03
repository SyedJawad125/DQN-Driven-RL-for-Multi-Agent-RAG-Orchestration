"""
LangGraph Graph Builder
Assembles nodes into a stateful graph with conditional routing.
"""
import logging
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import RAGState
from .nodes import (
    planner_node,
    retriever_node,
    web_search_node,
    rl_decision_node,
    answer_node,
    evaluator_node,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  ROUTING FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def route_after_rl(state: RAGState) -> Literal["retriever", "answer"]:
    """After RL decision: retrieve more OR answer now."""
    action = state.get("rl_action", "ANSWER_NOW")
    if action == "RETRIEVE_MORE":
        return "retriever"
    return "answer"


def route_after_planner(state: RAGState) -> Literal["retriever", "web_search"]:
    """After planning: if internet required AND no parallel, search first."""
    if state.get("requires_internet") and not state.get("parallel_execution"):
        return "web_search"
    return "retriever"


# ─────────────────────────────────────────────────────────────────────────────
#  GRAPH BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_rag_graph() -> StateGraph:
    """
    Build and compile the LangGraph RAG pipeline.

    Graph structure:
        planner → retriever ─────────────────────────────────────────┐
                          └→ rl_decision → RETRIEVE_MORE → retriever  │
                                       └→ ANSWER_NOW → answer ←───────┘
                                                      ↕ (parallel if needed)
                                              web_search (optional)
                                                      ↓
                                                  evaluator → END
    """
    graph = StateGraph(RAGState)

    # Add nodes
    graph.add_node("planner",    planner_node)
    graph.add_node("retriever",  retriever_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("rl_decision", rl_decision_node)
    graph.add_node("answer",     answer_node)
    graph.add_node("evaluator",  evaluator_node)

    # Entry point
    graph.set_entry_point("planner")

    # planner → retriever (always retrieve first)
    graph.add_edge("planner", "retriever")

    # retriever → rl_decision (always check RL after retrieval)
    graph.add_edge("retriever", "rl_decision")

    # rl_decision → conditional routing
    graph.add_conditional_edges(
        "rl_decision",
        route_after_rl,
        {
            "retriever": "retriever",   # RETRIEVE_MORE loops back
            "answer":    "answer",      # ANSWER_NOW proceeds
        },
    )

    # web_search runs before answer if planner requested internet
    graph.add_edge("web_search", "answer")

    # answer → evaluator
    graph.add_edge("answer", "evaluator")

    # evaluator → END
    graph.add_edge("evaluator", END)

    # Checkpointing (enables session memory + resume)
    checkpointer = MemorySaver()

    return graph.compile(checkpointer=checkpointer)


# Singleton
_graph_instance = None


def get_rag_graph():
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_rag_graph()
        logger.info("[GraphBuilder] LangGraph RAG pipeline compiled")
    return _graph_instance