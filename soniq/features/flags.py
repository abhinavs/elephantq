"""Feature flag helpers for Soniq optional capabilities."""

from soniq.settings import get_settings


def require_feature(flag_name: str, human_name: str) -> None:
    settings = get_settings()
    if not getattr(settings, flag_name):
        raise RuntimeError(
            f"{human_name} is disabled. Set SONIQ_{flag_name.upper()}=true to enable."
        )
