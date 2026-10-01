from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..container import Container
from ..domain import errors
from .routes import auth, chat, family
from .security import FailedAttempts, SessionCookie

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
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.container = c
    app.state.session_cookie = SessionCookie(secure=c.settings.cookie_secure)
    app.state.failed_attempts = FailedAttempts()
    app.add_exception_handler(errors.DomainError, _domain_error)

    for module in (auth, family, chat):
        app.include_router(module.router)
    app.include_router(auth.login)

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
