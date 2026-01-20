# v1 API Routers

from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.recommend import router as recommend_router

router = APIRouter()

router.include_router(health_router, tags=["Health"])
router.include_router(recommend_router, tags=["Recommendation"])
