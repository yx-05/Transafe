"""Enterprise Console API package (v2).

Mounted additively at ``/enterprise``. Contains no v1 handlers and modifies no
v1 route.
"""

from src.api.enterprise.router import router

__all__ = ["router"]
