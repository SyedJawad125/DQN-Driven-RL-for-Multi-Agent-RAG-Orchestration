Project Description:

A fully featured authentication system that includes user registration, login, password update, forgot password, OTP verification, and secure logout. The backend is built with Django, the frontend uses Next.js 14, and PostgreSQL is used as the database. The system follows a robust and secure authentication flow utilizing both access and refresh tokens.

Here is the short summary of project:

Deep Q-Network (DQN) / neural Q.
This project keeps the entire foundation and upgrades the three weak points. The RL brain is now a small neural network (DQN) that sees a richer 6-number description of each situation and has a separate "target network" to keep training stable. On first boot it pre-trains on 800 synthetic examples so it already knows the basics before seeing real users. The reward signal is now real — a new EvaluatorAgent scores every answer on factuality, coverage, hallucination risk, and conciseness using one LLM call, and that composite score drives the RL update instead of the old heuristic. And parallel execution actually works now: when the planner says "use both RAG and web search," they genuinely run at the same time via asyncio.gather()

About This Project:

This project focuses on building AI-powered chatbots capable of making intelligent decisions—determining when to retrieve additional information and when to generate responses. This approach helps reduce API costs while significantly improving response accuracy.

Say:

I build AI chatbots that intelligently decide when to search more data and when to answer, reducing API costs and improving accuracy.

---------------------------------------------

DQN-RAG → LangGraph Multi-Agent Platform:

User Query
    │
    ▼
n8n Workflow Trigger
    │
    ▼
Django REST API (FastAPI optional)
    │
    ▼
LangGraph Orchestrator
    ├── PlannerNode      → classifies query, builds execution plan
    ├── RetrieverNode    → ChromaDB vector search
    ├── WebSearchNode    → Tavily internet search (parallel)
    ├── EvaluatorNode    → scores quality (factuality, hallucination)
    ├── AnswerNode       → generates final answer
    └── RLDecisionNode   → DQN decides: retrieve more / re-rank / answer
         │
         ▼
    Redis Cache + PostgreSQL + ChromaDB
         │
         ▼
    n8n → Slack / Email / Webhook notifications


Why this beats your current system:

LangGraph gives you a visual, debuggable state machine instead of manual if/else routing
Built-in streaming, checkpointing, and human-in-the-loop support
CrewAI agents are drop-in for role-based tasks (researcher, writer, critic)
n8n automates your entire ops loop (alerts, retraining triggers, Slack reports)