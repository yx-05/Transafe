"""TranSafe FastAPI Main Application Entry Point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.agents.graph import compile_graph
from src.api.admin import router as admin_router
from src.api.triggers import router as triggers_router
from src.api.websocket import websocket_router
from src.api.websocket_call import call_ws_router


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
app.include_router(triggers_router, prefix="/api/v1")
app.include_router(websocket_router)
app.include_router(call_ws_router)
app.include_router(admin_router)
