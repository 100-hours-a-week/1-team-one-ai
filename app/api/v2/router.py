# app/api/v2/router.py
"""
v2 API Routers
- router = APIRouter()
"""

from fastapi import APIRouter

from app.api.v1.health import router as health_router
from app.api.v2.data import router as data_router
from app.api.v2.recommend import router as recommend_router

router = APIRouter()

router.include_router(health_router, tags=["Health"])
router.include_router(recommend_router, tags=["Recommendation"])
router.include_router(data_router, tags=["Data"])
