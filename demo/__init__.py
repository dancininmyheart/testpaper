__all__ = ["DemoService", "make_handler", "main"]


def __getattr__(name):
    if name == "DemoService":
        from .service import DemoService

        return DemoService
    if name in {"make_handler", "main"}:
        from .http_app import main, make_handler

        return {"main": main, "make_handler": make_handler}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
