"""Einstellungen aus der Umgebung (.env) – einmal beim Start gelesen, danach unveränderlich."""
import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_list(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in _env(name).split(",") if item.strip())


@dataclass(frozen=True)
class SmtpSettings:
    host: str = "smtp.office365.com"
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = ""
    debug: bool = False          # MAIL_DEBUG=1: Mails ins Log statt verschicken (lokale Tests)

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password)

    @classmethod
    def from_env(cls) -> "SmtpSettings":
        user = _env("SMTP_USER")
        return cls(
            host=_env("SMTP_HOST", cls.host),
            port=int(_env("SMTP_PORT", str(cls.port))),
            user=user,
            password=os.environ.get("SMTP_PASSWORD", ""),
            sender=_env("MAIL_FROM") or user,
            debug=_env("MAIL_DEBUG") == "1",
        )


@dataclass(frozen=True)
class LlmSettings:
    api_key: str = ""
    model: str = ""
    fallback_models: tuple[str, ...] = ()
    base_url: str = "https://openrouter.ai/api/v1"

    @classmethod
    def from_env(cls) -> "LlmSettings":
        return cls(api_key=_env("OPENROUTER_API_KEY"), model=_env("MODEL"),
                   fallback_models=_env_list("FALLBACK_MODELS"))


@dataclass(frozen=True)
class Settings:
    db_path: str = "/app/data/geschenke.db"
    app_url: str = "https://geschenke.nordhain-gmbh.de"
    admin_email: str = ""        # diese Person ist Admin und bekommt Mails bei Neuregistrierungen
    family_code: str = ""        # optionaler Ausweg zur Selbst-Registrierung; leer = nur per Einladung
    cookie_secure: bool = True
    api_key_days: int = 30       # Gültigkeit persönlicher KI-Zugänge (MCP)
    smtp: SmtpSettings = field(default_factory=SmtpSettings)
    llm: LlmSettings = field(default_factory=LlmSettings)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=_env("DB_PATH", cls.db_path),
            app_url=_env("APP_URL", cls.app_url),
            admin_email=_env("ADMIN_EMAIL"),
            family_code=_env("FAMILY_CODE"),
            cookie_secure=_env("COOKIE_SECURE", "true").lower() != "false",
            api_key_days=int(_env("API_KEY_DAYS", "30")),
            smtp=SmtpSettings.from_env(),
            llm=LlmSettings.from_env(),
        )
