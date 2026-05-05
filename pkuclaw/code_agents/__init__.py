"""Concrete agent implementations."""

__all__ = ["CodexAgent"]


def __getattr__(name: str):
    if name == "CodexAgent":
        from pkuclaw.code_agents.codex import CodexAgent

        return CodexAgent
    raise AttributeError(name)
