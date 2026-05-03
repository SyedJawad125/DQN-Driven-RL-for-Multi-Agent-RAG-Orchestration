"""
Graph Executor — bridges Django views and LangGraph.
"""
import asyncio
import logging
import time
import uuid
from typing import Any, Dict

from django.utils import timezone

from .graph_builder import get_rag_graph
from .state import RAGState
from apps.rag.models import Document, Query, Session, RLEpisodeSummary
from apps.rag.services.agents.rl_agent import RLDecisionAgent
from apps.rag.tasks import notify_n8n  # Celery task

logger = logging.getLogger(__name__)


class GraphExecutor:
    """
    Main entry point that replaces MultiAgentCoordinator.
    Used by views.py to run the full LangGraph pipeline.
    """

    def __init__(self):
        self.graph = get_rag_graph()
        self.rl_agent = RLDecisionAgent()

    async def execute(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the LangGraph pipeline and return a response dict
        compatible with your existing views.py / serializers.
        """
        start = time.time()
        query_id = str(uuid.uuid4())

        # Build initial state
        initial_state: RAGState = {
            "query": query,
            "session_id": context.get("session_id"),
            "document_id": context.get("document_id"),
            "document_filter": context.get("document_filter"),
            "top_k": context.get("top_k", 5),
            "strategy": context.get("strategy", "auto"),
            "query_type": "factual_question",
            "complexity": "medium",
            "requires_internet": False,
            "parallel_execution": False,
            "retrieved_chunks": [],
            "retrieval_scores": [],
            "internet_sources": [],
            "tavily_answer": None,
            "rl_action": "RETRIEVE_MORE",
            "rl_step_count": 0,
            "rl_confidence": 0.5,
            "rl_metadata": {},
            "final_answer": "",
            "answer_confidence": 0.7,
            "evaluation_result": {},
            "execution_trace": [],
            "error": None,
        }

        # LangGraph config (enables checkpointing per session)
        config = {"configurable": {"thread_id": query_id}}

        try:
            # Run graph
            final_state = await self.graph.ainvoke(initial_state, config=config)

            # For complex analytical queries, optionally use CrewAI
            if (final_state.get("complexity") == "complex"
                    and final_state.get("query_type") == "analytical_question"
                    and not final_state.get("error")):
                try:
                    from apps.rag.services.crew.rag_crew import get_research_crew
                    crew_answer = get_research_crew(
                        query=query,
                        context_chunks=final_state.get("retrieved_chunks", []),
                    )
                    if crew_answer:
                        final_state["final_answer"] = crew_answer
                        logger.info("[GraphExecutor] CrewAI answer used for complex query")
                except Exception as e:
                    logger.warning(f"[GraphExecutor] CrewAI failed, using LangGraph answer: {e}")

            # Persist RL episode
            self._save_rl_episode(final_state, query_id)

            # Trigger n8n notification (async via Celery)
            processing_time = time.time() - start
            self._trigger_n8n_event(query, final_state, query_id, processing_time)

            return self._build_response(final_state, query, query_id, start)

        except Exception as e:
            logger.error(f"[GraphExecutor] Pipeline failed: {e}", exc_info=True)
            raise

    def _save_rl_episode(self, state: RAGState, query_id: str) -> None:
        """Persist RL episode to DB (same as before)."""
        try:
            eval_result = state.get("evaluation_result", {})
            RLEpisodeSummary.objects.update_or_create(
                query_id=query_id,
                defaults={
                    "total_steps": state.get("rl_step_count", 0),
                    "total_reward": eval_result.get("composite_score", 0.5),
                    "final_confidence": state.get("answer_confidence", 0.7),
                    "actions_taken": [state.get("rl_action", "ANSWER_NOW")],
                    "used_internet": bool(state.get("internet_sources")),
                },
            )
        except Exception as e:
            logger.warning(f"[GraphExecutor] RL episode save failed: {e}")

    def _trigger_n8n_event(self, query, state, query_id, processing_time):
        """Fire-and-forget n8n webhook via Celery."""
        try:
            notify_n8n.delay({
                "event": "query_completed",
                "query_id": query_id,
                "query_text": query[:100],
                "verdict": state.get("evaluation_result", {}).get("verdict", "UNKNOWN"),
                "processing_time": round(processing_time, 2),
                "complexity": state.get("complexity"),
                "rl_steps": state.get("rl_step_count", 0),
            })
        except Exception as e:
            logger.debug(f"[n8n] Trigger skipped: {e}")

    def _build_response(self, state: RAGState, query: str, query_id: str, start: float) -> Dict:
        """Build response dict compatible with existing serializers."""
        processing_time = time.time() - start
        eval_result = state.get("evaluation_result", {})

        return {
            "answer": state.get("final_answer", ""),
            "confidence": state.get("answer_confidence", 0.7),
            "strategy_used": "langgraph_multiagent",
            "processing_time": processing_time,
            "retrieved_chunks": [
                {
                    "content": c.get("content", ""),
                    "score": c.get("score", 0.0),
                    "metadata": c.get("metadata", {}),
                }
                for c in state.get("retrieved_chunks", [])
            ],
            "internet_sources": state.get("internet_sources", []),
            "execution_steps": state.get("execution_trace", []),
            "source": "langgraph_v3",
            "agent_type": "langgraph_multiagent",
            "agents_used": [
                "PlannerNode", "RetrieverNode", "RLDecisionNode",
                "WebSearchNode", "AnswerNode", "EvaluatorNode",
            ],
            "query_type": state.get("query_type", "factual_question"),
            "evaluation_result": eval_result,
            "rl_metadata": {
                "query_id": query_id,
                "steps_taken": state.get("rl_step_count", 0),
                "last_action": state.get("rl_action", "ANSWER_NOW"),
                "epsilon": 0.3,
            },
        }


# Singleton
_executor = None


def get_executor() -> GraphExecutor:
    global _executor
    if _executor is None:
        _executor = GraphExecutor()
    return _executor