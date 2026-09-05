import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app import __version__
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.evaluation import router as evaluation_router
from app.api.settings import router as settings_router
from app.api.traces import router as traces_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware

configure_logging(settings.LOG_LEVEL)

logger = logging.getLogger("app")


class SPAStaticFiles(StaticFiles):
    """
    Serve the built Angular app: any path that is not a real file falls back
    to index.html so client-side routes survive a page reload. API paths are
    never rewritten - an unknown API route stays a JSON 404.
    """

    async def __call__(self, scope, receive, send) -> None:
        # Anything under /api/ that reached the static mount is an unknown API
        # route (or a disallowed method on one): report it as a JSON 404
        # through the app's error handlers, never as the SPA page or a 405.
        if scope["type"] == "http" and _is_api_path(scope.get("path", "")):
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        await super().__call__(scope, receive, send)

    async def get_response(self, path: str, scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as error:
            if error.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def _is_api_path(path: str) -> bool:
    return path.lstrip("/").startswith("api/")


def create_app(frontend_dist: Path | None = None) -> FastAPI:

    app = FastAPI(
        title="Insurance Claims RAG API",
        version=__version__,
        description=(
            "Answers questions from an insurance endorsement pack, citing the file "
            "and page for every fact, and refuses when the documents do not cover it."
        ),
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    register_error_handlers(app)

    app.include_router(settings_router)
    app.include_router(chat_router)
    app.include_router(documents_router)
    app.include_router(evaluation_router)
    app.include_router(traces_router)

    dist = settings.FRONTEND_DIST if frontend_dist is None else frontend_dist

    if dist.is_dir():
        app.mount("/", SPAStaticFiles(directory=dist, html=True), name="ui")
        logger.info("Serving frontend from %s", dist)
    else:
        @app.get("/", include_in_schema=False)
        def root():
            return {
                "name": "Insurance Claims RAG API",
                "version": __version__,
                "docs": "/docs",
                "frontend": "not built - run `npm run build` in frontend/ or `ng serve`",
            }

    return app


app = create_app()
