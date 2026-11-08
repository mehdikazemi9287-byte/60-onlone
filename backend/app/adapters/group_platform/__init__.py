"""Group platform port: one login, wallet and loyalty across the group's businesses.

`base.GroupPlatform` is the interface; `local.LocalGroupPlatform` serves it from this
database. A real shared platform replaces it by registering another implementation.
"""
from app.adapters.group_platform.registry import get_group_platform, register  # noqa: F401
