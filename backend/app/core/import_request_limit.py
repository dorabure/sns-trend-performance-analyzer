"""Public ASGI receive wrapper: bound multipart bytes before parser writes."""
import re

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

TOO_LARGE = {"status": "FAILED", "errors": [{"row": None, "field": "file",
    "code": "REQUEST_TOO_LARGE", "message": "Import request exceeds the size limit"}]}


class ImportRequestLimit:
    def __init__(self, app, max_bytes):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] != "POST" or
                not re.fullmatch(r"/api/v1/projects/[^/]+/imports/?", scope["path"])):
            return await self.app(scope, receive, send)
        # Reject on any over-limit declaration, but never trust a smaller declaration.
        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    continue
                if declared > self.max_bytes:
                    return await JSONResponse(TOO_LARGE, status_code=413)(scope, receive, send)
        size = 0

        async def limited_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > self.max_bytes:
                    # Installed Starlette closes partial spools; FastAPI rethrows
                    # public HTTPException. ImportRoute preserves the Import schema.
                    raise HTTPException(413, detail=TOO_LARGE)
            return message

        await self.app(scope, limited_receive, send)
