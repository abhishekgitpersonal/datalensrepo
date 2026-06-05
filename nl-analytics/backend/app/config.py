from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ollama_host: str = "http://localhost:11434"
    ollama_sql_model: str = "qwen2.5-coder:7b"       # strong model (retry / hard queries)
    ollama_sql_fast_model: str = "qwen2.5-coder:3b"  # fast model (first attempt)
    ollama_narrate_model: str = "llama3.1:8b"
    ollama_timeout_seconds: int = 120
    ollama_keep_alive: str = "30m"                   # keep models warm in RAM between requests

    storage_dir: str = "../storage"

    max_upload_mb: int = 100
    max_files_per_session: int = 15
    sql_row_limit: int = 10000
    sql_timeout_seconds: int = 30

    # CSV ingest / cleansing controls
    csv_infer_sample_rows: int = 200000
    cleansing_cast_ratio: float = 0.98
    outlier_clip_enabled: bool = False
    outlier_clip_lower_q: float = 0.01
    outlier_clip_upper_q: float = 0.99

    allowed_origins: str = "http://localhost:3000"

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        (p / "sessions").mkdir(parents=True, exist_ok=True)
        return p

    @property
    def sqlite_path(self) -> Path:
        return self.storage_path / "app.db"

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


settings = Settings()
