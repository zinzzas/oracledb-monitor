"""
Oracle 커넥션 풀 관리.

python-oracledb 는 별도 설정을 하지 않으면 기본적으로 Thin mode 로 동작한다.
Thin mode 는 Oracle Instant Client 설치가 필요 없고, 순수 TCP 로 리스너에 접속하므로
"서버 접속 불가, 클라이언트 접속만 가능" 조건에 정확히 부합한다.

connect_type_to_thick() 등을 절대 호출하지 않는다 (호출 시 Thick 모드로 전환되어
Instant Client 가 필요해짐).
"""
from __future__ import annotations  # Python 3.9 호환 (X | None 문법을 지연 평가)
import oracledb
from app.config import settings

_pool: oracledb.ConnectionPool | None = None


def init_pool() -> oracledb.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = oracledb.create_pool(
            user=settings.oracle_user,
            password=settings.oracle_password,
            dsn=settings.oracle_dsn,
            min=1,
            max=5,
            increment=1,
            timeout=30,  # 유휴 커넥션 회수(초)
        )
    return _pool


def get_pool() -> oracledb.ConnectionPool:
    if _pool is None:
        return init_pool()
    return _pool


def close_pool():
    global _pool
    if _pool is not None:
        _pool.close(force=True)
        _pool = None
