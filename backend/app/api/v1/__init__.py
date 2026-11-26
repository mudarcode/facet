from fastapi import APIRouter

from app.api.v1 import (
    activity,
    charts,
    dashboards,
    datasets,
    exports,
    jobs,
    meta,
    queries,
    transformations,
)

api_router = APIRouter(prefix="/api/v1")
for module in (
    meta,
    activity,
    datasets,
    queries,
    transformations,
    charts,
    dashboards,
    exports,
    jobs,
):
    api_router.include_router(module.router)
