from __future__ import annotations

import math

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .bridge import Bridge, BridgeError
from .config import Settings


def create_app(settings: Settings | None = None, bridge: Bridge | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    bridge = bridge or Bridge(settings)
    app = FastAPI(title="Local Dify Knowledge Bridge", docs_url=None, redoc_url=None, openapi_url=None)

    def require_token(authorization: str | None) -> None:
        expected = settings.auth_token
        if not expected or authorization != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.exception_handler(BridgeError)
    async def bridge_error(_: Request, exc: BridgeError):
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    @app.get("/health")
    async def health(authorization: str | None = Header(default=None)):
        require_token(authorization)
        return bridge.health()

    @app.post("/retrieval")
    async def retrieval(request: Request, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="valid JSON required") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="JSON object required")
        setting = body.get("retrieval_setting") or {}
        if not isinstance(setting, dict):
            raise HTTPException(status_code=422, detail="retrieval_setting must be an object")
        top_k = setting.get("top_k", body.get("top_k", 5))
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
            raise HTTPException(status_code=422, detail="top_k must be an integer between 1 and 20")
        threshold = setting.get("score_threshold", body.get("score_threshold", 0.0))
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise HTTPException(status_code=422, detail="score_threshold must be a finite number between 0 and 1")
        records = bridge.retrieve(body.get("query"), body.get("knowledge_id", ""), top_k, float(threshold))
        return {"records": records}

    @app.post("/ingest")
    async def ingest(request: Request, filename: str | None = None, x_filename: str | None = Header(default=None), authorization: str | None = Header(default=None)):
        require_token(authorization)
        incoming_filename = filename or x_filename
        content_type = request.headers.get("content-type", "")
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="upload exceeds 25 MB limit")
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or not hasattr(upload, "read"):
                raise HTTPException(status_code=422, detail="multipart requests require a file field")
            incoming_filename = incoming_filename or getattr(upload, "filename", None)
            raw = await upload.read()
        else:
            received = bytearray()
            async for piece in request.stream():
                received.extend(piece)
                if len(received) > settings.max_upload_bytes:
                    raise HTTPException(status_code=413, detail="upload exceeds 25 MB limit")
            raw = bytes(received)
        if len(raw) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="upload exceeds 25 MB limit")
        return bridge.ingest(incoming_filename or "", raw)

    return app


app = create_app()
