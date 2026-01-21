from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.core.logging import setup_logging

setup_logging()


app = FastAPI(
    title="Recommendation API",
    version="1.0.0",
)

app.include_router(v1_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"status": "ok"}
