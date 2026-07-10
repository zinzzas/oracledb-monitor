"""
전역 설정. .env 파일에서 값을 읽어온다.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    oracle_user: str
    oracle_password: str
    oracle_dsn: str  # host:port/service_name

    poll_interval_sec: int = 5
    slow_query_threshold_sec: int = 5
    sqlite_path: str = "./data/monitor.db"
    retention_hours: int = 24


settings = Settings()
