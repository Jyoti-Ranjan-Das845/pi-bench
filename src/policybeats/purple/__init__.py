"""
Purple Agent (Agent Under Test) for PolicyBeats.

Two implementations:
1. Rule-based (agent.py): Deterministic, for testing the benchmark itself
2. LLM-based (llm_agent.py): Realistic, for testing LLM compliance

Usage:
    # Rule-based (deterministic)
    from policybeats.purple import create_purple_agent, PurpleAgentMode
    app = create_purple_agent(PurpleAgentMode.COMPLIANT)

    # LLM-based (realistic)
    from policybeats.purple.llm_agent import run_all_episodes
    results = await run_all_episodes(runs_per_episode=12)

    # LLM as A2A server (for benchmarking guardrails)
    from policybeats.purple.llm_agent import create_llm_server, create_shieldgemma_server
    app = create_shieldgemma_server(port=8001)  # ShieldGemma via Ollama
    app = create_llm_server(model="gpt-4o-mini", port=8001)  # Any LiteLLM model

Supported Models:
    - OpenAI: gpt-4o, gpt-4o-mini, gpt-3.5-turbo
    - Ollama (OSS): ollama/shieldgemma, ollama/gemma2:9b, ollama/llama3.2
    - Google: gemini-pro, gemini-1.5-flash
    - Anthropic: claude-3-haiku, claude-3-sonnet
"""

from policybeats.purple.agent import create_purple_agent, PurpleAgentMode

# LLM-based server factories (lazy import to avoid litellm dependency)
def create_llm_server(model: str = "gpt-4o-mini", framework: str = "gdpr", port: int = 8001):
    """Create an LLM-backed Purple agent A2A server."""
    from policybeats.purple.llm_agent import create_llm_server as _create
    return _create(model=model, framework=framework, port=port)

def create_shieldgemma_server(port: int = 8001):
    """Create a ShieldGemma Purple agent server (requires Ollama)."""
    from policybeats.purple.llm_agent import create_shieldgemma_server as _create
    return _create(port=port)

def create_gemma_server(size: str = "9b", port: int = 8001):
    """Create a Gemma Purple agent server (requires Ollama)."""
    from policybeats.purple.llm_agent import create_gemma_server as _create
    return _create(size=size, port=port)

__all__ = [
    "create_purple_agent",
    "PurpleAgentMode",
    "create_llm_server",
    "create_shieldgemma_server",
    "create_gemma_server",
]
