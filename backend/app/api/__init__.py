"""HTTP surface for NOVA."""
from fastapi import APIRouter

from . import (
    approvals, auth, chat, content, desktop, files, integrations, memory, productivity, publishing,
    system, tasks, triggers, whatsapp, workflows,
)

api_router = APIRouter()
for module in (
    auth, tasks, chat, approvals, memory, content, files, integrations, productivity, publishing, system,
    whatsapp, triggers, desktop, workflows,
):
    api_router.include_router(module.router)

__all__ = ["api_router"]
