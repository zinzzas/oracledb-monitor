"""
오라클 접속만 독립적으로 검증하는 스크립트. FastAPI/스케줄러 없이 원인을 빠르게 좁힌다.

실행:
    python scripts/test_connection.py

단계:
  1) 순수 TCP 소켓으로 host:port 가 열려있는지 확인 (DSN 파싱 문제와 분리)
  2) python-oracledb 로 실제 로그인 시도
  3) 로그인 성공 시 v$osstat 한 줄 조회까지 확인 (권한 문제까지 한 번에 체크)
"""
from __future__ import annotations  # Python 3.9 호환 (X | None 문법을 지연 평가)
import socket
import sys
import re

sys.path.insert(0, ".")  # app 패키지를 찾기 위해

from app.config import settings  # noqa: E402
import oracledb  # noqa: E402


def parse_host_port(dsn: str):
    # host:port/service_name 또는 host:port:sid 형태 모두 대응
    m = re.match(r"^([^:/]+):(\d+)", dsn)
    if not m:
        return None, None
    return m.group(1), int(m.group(2))


def step1_tcp_check(host: str, port: int) -> bool:
    print(f"[1/3] TCP 연결 테스트 → {host}:{port}")
    try:
        with socket.create_connection((host, port), timeout=5):
            print("      ✅ TCP 연결 성공 (해당 host:port 는 열려있음)")
            return True
    except socket.timeout:
        print("      ❌ 타임아웃 — 방화벽이 패킷을 그냥 버리고 있음 (VPN 연결 확인 필요)")
    except ConnectionRefusedError:
        print("      ❌ Connection refused — host 는 응답했지만 그 포트에 리스너가 없음")
        print("         → 포트 번호가 맞는지, 방화벽이 RST 로 막고 있는 건 아닌지 확인")
    except socket.gaierror as e:
        print(f"      ❌ DNS 조회 실패: {e} — 호스트명이 맞는지 확인 (사내 DNS/VPN 필요할 수 있음)")
    except Exception as e:
        print(f"      ❌ 알 수 없는 오류: {e}")
    return False


def step2_oracle_login() -> oracledb.Connection | None:
    print(f"[2/3] Oracle 로그인 시도 → user={settings.oracle_user}, dsn={settings.oracle_dsn}")
    try:
        conn = oracledb.connect(
            user=settings.oracle_user,
            password=settings.oracle_password,
            dsn=settings.oracle_dsn,
        )
        print("      ✅ 로그인 성공")
        return conn
    except oracledb.DatabaseError as e:
        (error_obj,) = e.args
        print(f"      ❌ 로그인 실패 [{error_obj.full_code}] {error_obj.message}")
        if "ORA-12154" in str(e):
            print("         → TNS 이름을 못 찾음. DSN을 host:port/service_name 형식으로 직접 넣었는지 확인")
        if "ORA-01017" in str(e):
            print("         → 계정/비밀번호 오류")
        if "ORA-12514" in str(e) or "ORA-12505" in str(e):
            print("         → service_name(또는 SID) 오타. 리스너는 열려있지만 해당 서비스가 등록 안 됨")
        return None


def step3_query_check(conn: oracledb.Connection):
    print("[3/3] 권한 확인용 조회 (v$osstat)")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT stat_name, value FROM v$osstat WHERE stat_name = 'NUM_CPUS'"
            )
            row = cur.fetchone()
            print(f"      ✅ 조회 성공: {row}")
    except oracledb.DatabaseError as e:
        (error_obj,) = e.args
        print(f"      ❌ 조회 실패 [{error_obj.full_code}] {error_obj.message}")
        if "ORA-00942" in str(e) or "ORA-01031" in str(e):
            print("         → v$osstat 조회 권한 없음. DBA에게 다음 실행 요청:")
            print("           GRANT SELECT_CATALOG_ROLE TO " + settings.oracle_user + ";")


if __name__ == "__main__":
    host, port = parse_host_port(settings.oracle_dsn)
    if host and port:
        ok = step1_tcp_check(host, port)
        if not ok:
            print("\n⚠️  TCP 단계에서 막혔으므로 Oracle 로그인은 어차피 실패합니다.")
            print("    VPN 연결 여부 / host·port 오타 / 사내 방화벽 정책을 먼저 확인해주세요.")
            sys.exit(1)
    else:
        print("[1/3] DSN에서 host:port 를 파싱하지 못해 TCP 사전점검은 건너뜁니다.")
        print(f"      현재 DSN: {settings.oracle_dsn}")

    conn = step2_oracle_login()
    if conn:
        step3_query_check(conn)
        conn.close()
