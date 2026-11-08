from __future__ import annotations

from app.adapters.group_platform.base import GroupPlatform

_PLATFORMS: dict[str, GroupPlatform] = {}


def register(platform: GroupPlatform) -> None:
    _PLATFORMS[platform.name] = platform


def get_group_platform(name: str = "local") -> GroupPlatform:
    if not _PLATFORMS:
        from app.adapters.group_platform.local import LocalGroupPlatform
        register(LocalGroupPlatform())
    return _PLATFORMS[name]
