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

    # 대시보드 표시용 인스턴스 라벨 (MaxGauge의 "PROD11P" 같은 표시명).
    # 단일 인스턴스만 모니터링하므로 멀티 인스턴스 선택 드롭다운은 없고 라벨만 표시.
    instance_label: str = "ORACLE"

    # 알림 임계치 (CPU/MEM % 공통) - 카드 색상 단계와 동일한 기준
    alert_warn_pct: float = 60.0
    alert_high_pct: float = 70.0
    alert_crit_pct: float = 80.0

    # Active Sessions/Lock 전용 고빈도 폴링 (초). 메인 5초 수집 사이에 끝나는
    # REF CURSOR fetch처럼 짧은 실행을 놓치지 않기 위해 별도 스케줄러로 더 자주 돌린다.
    # V$SESSION/V$LOCK만 가벼게 조회하므로 1초 간격도 대부분의 Oracle 인스턴스에서 안전하나,
    # 인스턴스가 민감하면 .env에서 늘려서 조정할 것.
    fast_poll_interval_sec: float = 1.0
    fast_poll_enabled: bool = True


settings = Settings()
