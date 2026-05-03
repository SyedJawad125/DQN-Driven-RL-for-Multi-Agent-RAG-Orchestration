"""
LangGraph Node Implementations
Each function is a node in the graph — receives state, returns partial state update.
"""
import asyncio
import logging
import time
from typing import Any, Dict

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from django.conf import settings
from .state import RAGState
from apps.rag.services.core_services import (
    get_embedding_service, get_vector_store
)

logger = logging.getLogger(__name__)


def _get_llm() -> ChatGroq:
    """LangChain-compatible Groq LLM."""
    return ChatGroq(
        model=settings.GROQ_MODEL,
        temperature=0.3,
        api_key=settings.GROQ_API_KEY,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  NODE 1: PLANNER
# ─────────────────────────────────────────────────────────────────────────────

async def planner_node(state: RAGState) -> Dict[str, Any]:
    """
    Analyze query → set complexity, query_type, requires_internet, parallel_execution.
    """
    logger.info(f"[Planner] Analyzing: {state['query'][:60]}")

    llm = _get_llm()
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content="""You are a query planner. Analyze the query and return ONLY valid JSON.
No markdown. No explanation."""),
        HumanMessage(content=f"""Analyze this query: "{state['query']}"

Return JSON:
{{
  "query_type": "factual_question|analytical_question|search_query|document_query|summarization",
  "complexity": "simple|medium|complex",
  "requires_internet": true|false,
  "parallel_execution": true|false,
  "reasoning": "brief reason"
}}""")
    ])

    try:
        import json
        response = await llm.ainvoke(prompt.format_messages())
        text = response.content.strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        data = json.loads(text)

        trace_entry = {
            "node": "planner",
            "timestamp": time.time(),
            "output": data,
        }

        return {
            "query_type": data.get("query_type", "factual_question"),
            "complexity": data.get("complexity", "medium"),
            "requires_internet": data.get("requires_internet", False),
            "parallel_execution": data.get("parallel_execution", False),
            "execution_trace": state.get("execution_trace", []) + [trace_entry],
        }

    except Exception as e:
        logger.error(f"[Planner] Failed: {e}")
        return {
            "query_type": "factual_question",
            "complexity": "medium",
            "requires_internet": False,
            "parallel_execution": False,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  NODE 2: RETRIEVER
# ─────────────────────────────────────────────────────────────────────────────

async def retriever_node(state: RAGState) -> Dict[str, Any]:
    """
    ChromaDB vector search → retrieved_chunks.
    Supports filtering by document_id OR document_filter (filename).
    """
    query = state["query"]
    top_k = state.get("top_k", 5)

    logger.info(f"[Retriever] Searching {top_k} chunks for: {query[:50]}")

    try:
        embedding_service = get_embedding_service()
        vector_store = get_vector_store()

        query_embedding = embedding_service.embed_text(query)

        # Build filter
        filter_dict = None
        if state.get("document_id"):
            filter_dict = {"document_id": {"$eq": str(state["document_id"])}}
        elif state.get("document_filter"):
            filter_dict = {"source": {"$eq": state["document_filter"]}}

        results = vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filter=filter_dict,
        )

        chunks = [
            {
                "content": r.get("content", ""),
                "score": r.get("score", 0.0),
                "metadata": r.get("metadata", {}),
            }
            for r in results
        ]

        # Merge with existing (dedup by content)
        existing = state.get("retrieved_chunks", [])
        seen = {c["content"] for c in existing}
        merged = existing + [c for c in chunks if c["content"] not in seen]

        avg_score = sum(c["score"] for c in merged) / max(len(merged), 1)

        logger.info(f"[Retriever] Got {len(merged)} total chunks (avg_score={avg_score:.2f})")

        return {
            "retrieved_chunks": merged,
            "rl_confidence": avg_score,
            "execution_trace": state.get("execution_trace", []) + [{
                "node": "retriever",
                "timestamp": time.time(),
                "chunks_found": len(merged),
                "avg_score": avg_score,
            }],
        }

    except Exception as e:
        logger.error(f"[Retriever] Error: {e}")
        return {"retrieved_chunks": [], "rl_confidence": 0.0}


# ─────────────────────────────────────────────────────────────────────────────
#  NODE 3: WEB SEARCH
# ─────────────────────────────────────────────────────────────────────────────

async def web_search_node(state: RAGState) -> Dict[str, Any]:
    """
    Tavily web search → internet_sources.
    Only runs if requires_internet=True.
    """
    if not state.get("requires_internet", False):
        return {}

    logger.info(f"[WebSearch] Searching for: {state['query'][:50]}")

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)

        response = client.search(
            query=state["query"],
            search_depth="advanced",
            max_results=5,
            include_answer=True,
        )

        sources = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", "")[:500],
                "score": r.get("score", 0.0),
            }
            for r in response.get("results", [])
        ]

        return {
            "internet_sources": sources,
            "tavily_answer": response.get("answer", ""),
            "execution_trace": state.get("execution_trace", []) + [{
                "node": "web_search",
                "timestamp": time.time(),
                "sources_found": len(sources),
            }],
        }

    except Exception as e:
        logger.error(f"[WebSearch] Error: {e}")
        return {"internet_sources": [], "tavily_answer": ""}


# ─────────────────────────────────────────────────────────────────────────────
#  NODE 4: RL DECISION
# ─────────────────────────────────────────────────────────────────────────────

async def rl_decision_node(state: RAGState) -> Dict[str, Any]:
    """
    DQN decides next action: ANSWER_NOW / RETRIEVE_MORE / RE_RANK.
    Imports your existing RLDecisionAgent — no rewrite needed.
    """
    from apps.rag.services.agents.rl_agent import RLDecisionAgent
    from apps.rag.services.agents.base_agent import AgentState as OldAgentState

    step_count = state.get("rl_step_count", 0)

    # Force answer if max steps reached
    if step_count >= 5:
        return {
            "rl_action": "ANSWER_NOW",
            "rl_step_count": step_count + 1,
        }

    # Build a thin OldAgentState to reuse your existing DQN
    old_state = OldAgentState(agent_name="rl", query=state["query"])
    old_state.metadata = {
        "retrieved_chunks": state.get("retrieved_chunks", []),
        "relevance_check": {"score": state.get("rl_confidence", 0.5)},
        "query_complexity": state.get("complexity", "medium"),
        "rl_step_count": step_count,
    }
    if state.get("internet_sources"):
        old_state.metadata["search_results"] = {"sources": state["internet_sources"]}

    rl_agent = RLDecisionAgent()
    result = await rl_agent.execute(old_state)
    action = result.output.strip()

    return {
        "rl_action": action,
        "rl_step_count": step_count + 1,
        "execution_trace": state.get("execution_trace", []) + [{
            "node": "rl_decision",
            "timestamp": time.time(),
            "action": action,
            "step": step_count + 1,
        }],
    }


# ─────────────────────────────────────────────────────────────────────────────
#  NODE 5: ANSWER GENERATOR
# ─────────────────────────────────────────────────────────────────────────────

async def answer_node(state: RAGState) -> Dict[str, Any]:
    """
    Generate final answer from chunks + internet sources using LangChain.
    """
    logger.info("[Answer] Generating final answer")

    chunks = state.get("retrieved_chunks", [])
    sources = state.get("internet_sources", [])

    # Build context
    context_parts = []
    for i, chunk in enumerate(chunks[:6], 1):
        context_parts.append(f"[Doc {i}]\n{chunk['content'][:400]}")
    for i, src in enumerate(sources[:3], 1):
        context_parts.append(f"[Web {i}: {src.get('title','')}]\n{src.get('content','')[:300]}")

    if state.get("tavily_answer"):
        context_parts.append(f"[Web Summary]\n{state['tavily_answer']}")

    context_text = "\n\n".join(context_parts) or "No context available."

    llm = _get_llm()
    prompt = ChatPromptTemplate.from_messages([
        SystemMessage(content="""You are a precise AI assistant.
Answer using ONLY the provided context.
If the context doesn't contain the answer, say so clearly.
Always cite your sources (Doc 1, Web 2, etc.)."""),
        HumanMessage(content=f"""Context:
{context_text}

Question: {state['query']}

Answer:""")
    ])

    try:
        response = await llm.ainvoke(prompt.format_messages())
        answer = response.content.strip()

        return {
            "final_answer": answer,
            "execution_trace": state.get("execution_trace", []) + [{
                "node": "answer",
                "timestamp": time.time(),
                "answer_length": len(answer),
            }],
        }
    except Exception as e:
        logger.error(f"[Answer] Error: {e}")
        return {"final_answer": "I encountered an error generating an answer.", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
#  NODE 6: EVALUATOR
# ─────────────────────────────────────────────────────────────────────────────

async def evaluator_node(state: RAGState) -> Dict[str, Any]:
    """
    Score answer quality using your existing EvaluatorAgent.
    Result becomes the RL reward signal.
    """
    from apps.rag.services.agents.evaluator_agent import EvaluatorAgent
    from apps.rag.services.agents.base_agent import AgentState as OldAgentState
    from apps.rag.services.core_services import get_llm_service

    evaluator = EvaluatorAgent(llm_service=get_llm_service())
    old_state = OldAgentState(agent_name="evaluator", query=state["query"])

    eval_result = await evaluator.evaluate(
        query=state["query"],
        answer=state.get("final_answer", ""),
        chunks=state.get("retrieved_chunks", []),
        state=old_state,
    )

    logger.info(
        f"[Evaluator] verdict={eval_result.verdict} | "
        f"composite={eval_result.composite_score:.3f}"
    )

    return {
        "evaluation_result": eval_result.to_dict(),
        "answer_confidence": eval_result.composite_score,
        "execution_trace": state.get("execution_trace", []) + [{
            "node": "evaluator",
            "timestamp": time.time(),
            "verdict": eval_result.verdict,
            "composite_score": eval_result.composite_score,
        }],
    }