""


def __getattr__(name):
    if name == "br_daily_briefing":
        import importlib.util
        import sys
        from pathlib import Path

        _spec = importlib.util.spec_from_file_location(
            "briefing.br_daily_briefing",
            Path(__file__).parent / "br-daily-briefing.py",
        )
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules["briefing.br_daily_briefing"] = _mod
        _spec.loader.exec_module(_mod)
        globals()["br_daily_briefing"] = _mod
        return _mod
    raise AttributeError(f"module 'briefing' has no attribute {name!r}")
