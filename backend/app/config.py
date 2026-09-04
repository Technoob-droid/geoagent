import os
from pathlib import Path
from pydantic_settings import BaseSettings

# Absolute reference to root directory
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    PROJECT_NAME: str = "GeoAgent"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # LLM Settings
    OPENAI_API_KEY: str = ""
    DEFAULT_MODEL: str = "gpt-4o"
    TEMPERATURE: float = 0.0

    # Spatial Storage Paths
    DUCKDB_DATABASE_PATH: str = str(ROOT_DIR / "backend" / "app" / "data" / "storage" / "geoagent.duckdb")
    SEEDS_DIR: str = str(ROOT_DIR / "backend" / "app" / "data" / "seeds")
    NOMINATIM_USER_AGENT: str = "geoagent-app"

    class Config:
        env_file = str(ROOT_DIR / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()

# Ensure required storage directories exist
os.makedirs(os.path.dirname(settings.DUCKDB_DATABASE_PATH), exist_ok=True)
os.makedirs(settings.SEEDS_DIR, exist_ok=True)