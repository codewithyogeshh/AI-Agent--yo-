"""Tool package — importing it registers every capability NOVA has."""
from .base import REGISTRY, Tool, ToolContext, ToolResult, catalog_text, get_tool, list_tools, register, tool

from . import web  # noqa: F401,E402
from . import files  # noqa: F401,E402
from . import memory  # noqa: F401,E402
from . import content  # noqa: F401,E402
from . import productivity  # noqa: F401,E402
from . import youtube  # noqa: F401,E402
from . import instagram  # noqa: F401,E402
from . import desktop  # noqa: F401,E402

__all__ = [
    "REGISTRY",
    "Tool",
    "ToolContext",
    "ToolResult",
    "catalog_text",
    "get_tool",
    "list_tools",
    "register",
    "tool",
]
