from fastapi import APIRouter

from app.api.audits import router as audits_router
from app.api.datasets import router as datasets_router
from app.api.query import router as query_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(datasets_router)
api_router.include_router(audits_router)
api_router.include_router(query_router)
