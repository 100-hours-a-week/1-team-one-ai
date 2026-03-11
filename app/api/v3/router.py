# app/api/v3/router.py
"""
v3 API Routers
- router = APIRouter()
"""

from fastapi import APIRouter

from app.api.v3.data import router as data_router
from app.api.v3.recommend import router as recommend_router

router = APIRouter()

router.include_router(recommend_router, tags=["Recommendation"])
router.include_router(data_router, tags=["Data"])
