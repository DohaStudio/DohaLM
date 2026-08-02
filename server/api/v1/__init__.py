"""Version 1 API routers."""

from fastapi import APIRouter

from server.api.v1.chat import router as chat_router
from server.api.v1.models import router as models_router


def api_router() -> APIRouter:
    router = APIRouter()
    router.include_router(models_router)
    router.include_router(chat_router)
    return router
