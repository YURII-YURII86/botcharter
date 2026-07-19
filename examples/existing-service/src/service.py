from __future__ import annotations


def summarize_note(text: str) -> str:
    """Return a compact plain-text summary for the synthetic demo."""
    return " ".join(text.split())[:280]
