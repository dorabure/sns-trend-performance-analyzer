import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException

from app.core.config import get_settings
from app.core.import_request_limit import TOO_LARGE
from app.db.session import SessionLocal
from app.dto.normalized import ValidationError
from app.providers.base import CsvDatasetType
from app.services.import_service import ImportFailure, ImportResult, ImportService, error_json


class ImportRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                return await original(request)
            except HTTPException as exc:
                if exc.status_code == 413:
                    return JSONResponse(status_code=413, content=TOO_LARGE)
                return JSONResponse(status_code=exc.status_code, content={"detail": "Import request could not be parsed"})
            except RequestValidationError as exc:
                # FastAPI normally echoes invalid input. Never echo multipart values.
                errors = [{"loc": error["loc"], "type": error["type"],
                           "msg": "Import request field is missing or invalid"} for error in exc.errors()]
                return JSONResponse(status_code=422, content={"detail": errors})
            except Exception:
                return JSONResponse(status_code=500, content={"status": "FAILED", "errors": [
                    {"row": None, "field": "system", "code": "IMPORT_DATABASE_ERROR",
                     "message": "Import could not be completed"}]})
        return handle


router = APIRouter(route_class=ImportRoute)


def get_import_service() -> ImportService:
    return ImportService(SessionLocal)


def safe_filename(value: str | None) -> str:
    filename = (value or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or filename in (".", "..") or len(filename) > 255 or re.search(r"[\x00-\x1f\x7f]", filename):
        raise ImportFailure(400, ValidationError(None, "file", "INVALID_FILENAME", "Upload filename is invalid"))
    return filename


@router.post("/projects/{project_id}/imports", response_model=ImportResult, tags=["imports"])
def import_csv(project_id: UUID, import_type: Annotated[CsvDatasetType, Form()],
               file: Annotated[UploadFile, File()],
               service: Annotated[ImportService, Depends(get_import_service)]):
    path = None
    import_id = None
    try:
        filename = safe_filename(file.filename)
        import_id, started = service.start(project_id, import_type, filename)
        try:
            with tempfile.NamedTemporaryFile(prefix="sns_import_", suffix=".csv", delete=False) as temporary:
                path = Path(temporary.name)
                size = 0
                limit = get_settings().max_import_file_size_bytes
                while chunk := file.file.read(min(64 * 1024, limit + 1)):
                    size += len(chunk)
                    if size > limit:
                        raise service.fail(import_id, ValidationError(None, "file", "FILE_TOO_LARGE",
                                                                      "CSV exceeds the upload size limit"), 413)
                    temporary.write(chunk)
        except ImportFailure:
            raise
        except Exception:
            raise service.fail(import_id, ValidationError(None, "file", "FILE_UNREADABLE",
                                                          "Upload could not be read"), 500) from None
        return service.run(import_id, started, project_id, import_type, path)
    except ImportFailure as exc:
        body = asdict(exc.result) if exc.result else {"status": "FAILED", "errors": [error_json(exc.error)]}
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(body))
    finally:
        file.file.close()
        if path is not None:
            path.unlink(missing_ok=True)
