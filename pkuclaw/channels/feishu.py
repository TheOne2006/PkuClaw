from __future__ import annotations

from pkuclaw.core.router import route_message


def handle_text_message(text: str) -> str:
    """Pure message handler shared by Feishu event code and tests."""
    return route_message(text)
