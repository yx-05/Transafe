"""Production entry point for Cloud Studio — serves frontend + backend on one port."""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

# Ensure env is loaded
load_dotenv()

# Import all routers
from src.api.admin import router as admin_router
from src.api.auth import router as auth_router
from src.api.enterprise import router as enterprise_router
from src.api.enterprise_demo import router as enterprise_demo_router
from src.api.enterprise_ws import enterprise_ws_router
from src.api.triggers import router as triggers_router
from src.api.websocket import websocket_router
from src.api.websocket_call import call_ws_router
from src.agents.graph import compile_graph

import logging

# Filter polling noise
class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("/call/active") == -1

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    app.state.compiled_graph = compile_graph()
    yield


app = FastAPI(
    title="TranSafe API",
    description="Real-Time AI-Powered Scam Protection Backend Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(triggers_router, prefix="/api/v1")
app.include_router(websocket_router)
app.include_router(call_ws_router)
app.include_router(admin_router)

# v2 Enterprise layer
app.include_router(enterprise_router)
app.include_router(enterprise_ws_router)
app.include_router(enterprise_demo_router)

# Serve frontend static files (built dist/) — mounted LAST so API/WS routes win.
# We mount /assets at their own path, and add a catch-all GET fallback for SPA routing.
# The catch-all only fires for GET requests to paths NOT matched by any explicit router.
frontend_dist = Path(__file__).parent / "static"
if frontend_dist.exists():
    # Mount static assets at /assets (where Vite outputs them)
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    # SPA fallback: serve index.html for any non-file GET that wasn't matched by a router.
    # FastAPI evaluates routes in registration order, so all API routers above are matched first.
    from fastapi import Request
    from fastapi.responses import FileResponse

    index_path = frontend_dist / "index.html"

    @app.get("/")
    @app.head("/")
    async def serve_index():
        return FileResponse(str(index_path))

    @app.get("/{full_path:path}")
    @app.head("/{full_path:path}")
    async def spa_fallback(full_path: str, request: Request):
        # Try to serve the actual file from dist
        file_path = frontend_dist / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        # SPA fallback — return index.html for client-side routing
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"detail": "Not Found"}

    print(f"[PROD] Serving frontend from {frontend_dist}")
else:
    print(f"[PROD] No frontend dist found at {frontend_dist}, API-only mode")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
