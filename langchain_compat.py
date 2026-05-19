from __future__ import annotations


def ensure_langchain_root_globals() -> None:
    """Fill legacy root globals expected by some langchain-core releases."""
    try:
        import langchain  # type: ignore
    except Exception:
        return
    defaults = {
        "verbose": False,
        "debug": False,
        "llm_cache": None,
    }
    for name, value in defaults.items():
        if not hasattr(langchain, name):
            setattr(langchain, name, value)
