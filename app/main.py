"""Einstieg für uvicorn: `uvicorn app.main:app`."""
from .config import Settings
from .container import Container
from .web import create_app

app = create_app(Container(Settings.from_env()))
