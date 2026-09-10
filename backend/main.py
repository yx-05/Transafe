"""TranSafe FastAPI Main Application Entry Point."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.agents.graph import compile_graph
from src.api.admin import router as admin_router
from src.api.auth import router as auth_router
from src.api.enterprise import router as enterprise_router
from src.api.enterprise_demo import router as enterprise_demo_router
from src.api.enterprise_ws import enterprise_ws_router
from src.api.triggers import router as triggers_router
from src.api.websocket import websocket_router
from src.api.websocket_call import call_ws_router

import logging

load_dotenv()

# Filter out high-frequency /call/active polling noise from Uvicorn access log
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("/call/active") == -1

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan context manager for startup pre-compilation."""
    app.state.compiled_graph = compile_graph()
    yield


app = FastAPI(
    title="TranSafe API",
    description="Real-Time AI-Powered Scam Protection Backend Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Custom exception handler wrapping HTTP errors in standard response envelope."""
    if isinstance(exc.detail, dict):
        error_payload = exc.detail
    else:
        code = "UNAUTHORIZED" if exc.status_code == 401 else "ERROR"
        error_payload = {
            "code": code,
            "message": str(exc.detail),
            "details": {},
        }

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "data": None,
            "error": error_payload,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check() -> dict[str, Any]:
    """Health check endpoint returning system status."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "services": {
            "supabase": "connected",
            "supabase_pgvector": "connected",
            "groq": "connected",
            "tavily": "connected",
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }


# Mount API routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(triggers_router, prefix="/api/v1")
app.include_router(websocket_router)
app.include_router(call_ws_router)
app.include_router(admin_router)

# ── v2 Enterprise layer (additive; no v1 route is modified) ──────────────────
app.include_router(enterprise_router)
app.include_router(enterprise_ws_router)
app.include_router(enterprise_demo_router)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
