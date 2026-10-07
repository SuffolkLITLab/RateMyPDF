"""Bound request bodies before multipart parsing, including chunked uploads."""
import os

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 20 * 1024 * 1024))
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024
JOB_TIMEOUT = int(os.getenv("JOB_TIMEOUT", "180"))
if MAX_UPLOAD_BYTES <= 0 or JOB_TIMEOUT <= 0:
    raise ValueError("Upload and job limits must be positive")


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_REQUEST_BYTES:
            response = JSONResponse({"detail": "Upload is too large or has an invalid length."}, status_code=413)
            return await response(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > MAX_REQUEST_BYTES:
                raise HTTPException(413, "Upload is too large.")
            return message

        await self.app(scope, limited_receive, send)
