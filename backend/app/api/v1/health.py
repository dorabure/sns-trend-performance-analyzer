from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok", "error"]
    database: Literal["connected", "disconnected"]


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def health(response: Response, db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        response.status_code = 503
        return HealthResponse(status="error", database="disconnected")
    return HealthResponse(status="ok", database="connected")
