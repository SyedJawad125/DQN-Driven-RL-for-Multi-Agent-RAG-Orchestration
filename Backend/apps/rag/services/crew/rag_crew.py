"""
CrewAI Research Crew
For complex analytical queries that need multi-perspective synthesis.
Triggered by PlannerAgent when complexity=complex AND query_type=analytical.
"""
from crewai import Agent, Task, Crew, Process
from crewai_tools import TavilySearchResults
from langchain_groq import ChatGroq
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def get_research_crew(query: str, context_chunks: list) -> str:
    """
    Run a 3-agent CrewAI pipeline for deep analytical queries.

    Agents:
        1. Researcher   — finds all relevant information
        2. Analyst      — evaluates and cross-checks claims
        3. Writer       — crafts the final polished answer

    Returns:
        Final synthesized answer string.
    """
    llm = ChatGroq(
        model=settings.GROQ_MODEL,
        temperature=0.3,
        api_key=settings.GROQ_API_KEY,
    )

    context_text = "\n\n".join(
        f"[{i+1}] {c['content'][:400]}"
        for i, c in enumerate(context_chunks[:5])
    )

    # ── Agents ────────────────────────────────────────────────────────────

    researcher = Agent(
        role="Senior Research Analyst",
        goal="Find all relevant information to answer the user's query comprehensively",
        backstory="""You are an expert researcher with 15 years of experience.
You excel at synthesizing information from multiple sources and identifying key facts.""",
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    analyst = Agent(
        role="Critical Analyst",
        goal="Evaluate information quality, identify gaps, and flag any contradictions",
        backstory="""You are a rigorous analyst who checks every claim for accuracy.
You identify when information is missing, contradictory, or needs verification.""",
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    writer = Agent(
        role="Technical Writer",
        goal="Craft a clear, accurate, well-structured answer the user will find genuinely useful",
        backstory="""You write precise, professional answers that are comprehensive but concise.
You always cite your sources and structure information logically.""",
        llm=llm,
        verbose=True,
        allow_delegation=False,
    )

    # ── Tasks ─────────────────────────────────────────────────────────────

    research_task = Task(
        description=f"""Research this query thoroughly using the provided context:

Query: {query}

Available Context:
{context_text}

Extract ALL relevant facts, data points, and insights from the context.
Note any gaps in the available information.""",
        expected_output="A comprehensive list of relevant facts and insights with source references",
        agent=researcher,
    )

    analysis_task = Task(
        description=f"""Critically analyze the research findings for the query: "{query}"

Review the researcher's findings and:
1. Identify the most important and reliable information
2. Flag any contradictions or uncertainties
3. Determine what's missing and whether it matters
4. Rate the overall quality of available information (high/medium/low)""",
        expected_output="A critical analysis with quality assessment and gap identification",
        agent=analyst,
        context=[research_task],
    )

    writing_task = Task(
        description=f"""Write the final answer to: "{query}"

Use the research and analysis to craft a response that:
- Directly answers the question
- Is backed by the available evidence
- Acknowledges any limitations or gaps
- Is concise but complete (aim for 150-400 words)
- Cites document sources used""",
        expected_output="A polished, accurate, well-cited answer to the user's query",
        agent=writer,
        context=[research_task, analysis_task],
    )

    # ── Crew ──────────────────────────────────────────────────────────────

    crew = Crew(
        agents=[researcher, analyst, writer],
        tasks=[research_task, analysis_task, writing_task],
        process=Process.sequential,
        verbose=True,
    )

    try:
        result = crew.kickoff()
        return str(result)
    except Exception as e:
        logger.error(f"[CrewAI] Failed: {e}")
        return ""