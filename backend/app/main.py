from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router
from app.api.v1.imports import router as imports_router
from app.api.v1.settings import router as settings_router
from app.api.v1.my_account import router as my_account_router
from app.api.v1.trends import router as trends_router
from app.api.v1.competitors import router as competitors_router
from app.api.v1.gap_analysis import router as gap_analysis_router
from app.api.v1.overview import router as overview_router
from app.api.v1.insights import router as insights_router
from app.api.v1.providers import router as providers_router
from app.api.v1.x_oauth import router as x_oauth_router
from app.api.v1.instagram_oauth import router as instagram_oauth_router
from app.core.oauth_log_filter import install_oauth_access_filter
from app.api.v1.job_operations import router as job_operations_router
from app.core.config import get_settings
from app.db.session import engine, SessionLocal
from app.services.import_recovery import recover_interrupted_imports
from app.core.import_request_limit import ImportRequestLimit


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        recover_interrupted_imports(SessionLocal)
        yield
    finally:
        engine.dispose()


app = FastAPI(title="SNS Trend & Performance Analyzer", lifespan=lifespan)
install_oauth_access_filter()
app.add_middleware(ImportRequestLimit, max_bytes=get_settings().max_import_request_size_bytes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Accept", "Content-Type"],
)
app.include_router(router, prefix="/api/v1")
app.include_router(imports_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(my_account_router, prefix="/api/v1")
app.include_router(trends_router, prefix="/api/v1")
app.include_router(competitors_router, prefix="/api/v1")
app.include_router(gap_analysis_router, prefix="/api/v1")
app.include_router(overview_router, prefix="/api/v1")
app.include_router(insights_router, prefix="/api/v1")
app.include_router(providers_router, prefix="/api/v1")
app.include_router(x_oauth_router, prefix="/api/v1")
app.include_router(instagram_oauth_router, prefix="/api/v1")
app.include_router(job_operations_router, prefix="/api/v1")
