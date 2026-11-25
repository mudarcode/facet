from fastapi import APIRouter

from app.api.v1 import datasets, jobs, meta, queries

api_router = APIRouter(prefix="/api/v1")
for module in (meta, datasets, queries, jobs):
    api_router.include_router(module.router)
