from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/cs_mvp.db"
    runs_dir: str = "runs"
    langfuse_enabled: bool = False
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    def ensure_directories(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.runs_dir).mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    load_dotenv()
    langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_enabled_flag = os.getenv("LANGFUSE_ENABLED", "").strip().lower()
    settings = Settings(
        db_path=os.getenv("DB_PATH", "data/cs_mvp.db"),
        runs_dir=os.getenv("RUNS_DIR", "runs"),
        langfuse_enabled=(
            False
            if langfuse_enabled_flag in {"0", "false", "no", "off"}
            else (
                langfuse_enabled_flag in {"1", "true", "yes", "on"}
                or bool(langfuse_public_key and langfuse_secret_key)
            )
        ),
        langfuse_host=os.getenv("LANGFUSE_HOST"),
        langfuse_public_key=langfuse_public_key,
        langfuse_secret_key=langfuse_secret_key,
    )
    settings.ensure_directories()
    return settings
