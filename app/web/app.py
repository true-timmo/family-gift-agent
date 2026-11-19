import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.routing import Route

from ..container import Container
from ..jobs import periodic
from ..domain import errors
from .mcp_gateway import McpGateway, RedactKeysFilter
from .routes import auth, chat, family
from .security import FailedAttempts, SessionCookie
from .static_assets import IndexPage, RevalidatedStaticFiles

STATIC = Path(__file__).parent.parent / "static"

# Fachlicher Fehler → HTTP-Status. Spezifische Klassen zuerst, DomainError als Rückfall.
_STATUS = {
    errors.NotFoundError: 404,
    errors.ConflictError: 409,
    errors.PermissionDeniedError: 403,
    errors.AuthenticationError: 401,
    errors.RateLimitError: 429,
    errors.DomainError: 400,
}


async def _domain_error(request: Request, exc: errors.DomainError) -> JSONResponse:
    status = next(code for cls, code in _STATUS.items() if isinstance(exc, cls))
    return JSONResponse({"detail": str(exc)}, status_code=status)


def create_app(c: Container) -> FastAPI:
    mcp = McpGateway(c.tools, c.api_keys, c.admins)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with (mcp.lifespan(), periodic(3600, c.api_keys.send_reminders, "Erinnerung KI-Zugang"),
                    periodic(3600, c.presence.send_reminders, "Erinnerung lange nicht da")):
            yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.container = c
    app.state.session_cookie = SessionCookie(secure=c.settings.cookie_secure)
    app.state.failed_attempts = FailedAttempts()
    app.add_exception_handler(errors.DomainError, _domain_error)

    for module in (auth, family, chat):
        app.include_router(module.router)
    app.include_router(auth.login)
    # MCP für eigene KI-Assistenten: Schlüssel im Header oder (für einfache Programme) in der Adresse
    app.router.routes += [Route("/mcp", mcp), Route("/mcp/{key}", mcp)]
    logging.getLogger("uvicorn.access").addFilter(RedactKeysFilter())

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    index_page = IndexPage(STATIC)

    @app.get("/")
    def index():
        return index_page.response()

    app.mount("/static", RevalidatedStaticFiles(directory=STATIC), name="static")
    return app
