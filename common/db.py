"""
SQL Server(카페24 MSSQL) 연결 — 접속 정보는 코드에 넣지 않고 Streamlit Secrets 에서 읽습니다.

Secrets 형식 (.streamlit/secrets.toml 또는 Streamlit Cloud > Settings > Secrets):

    [mssql]
    server = "sql19-001.cafe24.com"   # 카페24 '서비스 접속 정보'의 DB 접속 주소
    port = 1433
    database = "DB이름"
    user = "DB아이디"
    password = "DB비밀번호"

드라이버: pymssql (pip 설치만으로 동작, Streamlit Cloud·리눅스 서버 모두 사용 가능)
"""
import socket

import pymssql
import streamlit as st


def settings() -> dict | None:
    """Secrets 의 [mssql] 설정. 없으면 None"""
    try:
        cfg = dict(st.secrets["mssql"])
    except (KeyError, FileNotFoundError):
        return None
    missing = [k for k in ("server", "database", "user", "password") if not cfg.get(k)]
    return None if missing else cfg


def connect(timeout: int = 15):
    """새 DB 연결. 쓰고 나면 close() 하세요 (with 문 사용 권장)."""
    cfg = settings()
    if cfg is None:
        raise RuntimeError("DB 접속 정보(Secrets의 [mssql])가 설정되지 않았습니다.")
    return pymssql.connect(
        server=cfg["server"], port=str(cfg.get("port", 1433)),
        user=cfg["user"], password=cfg["password"], database=cfg["database"],
        login_timeout=timeout, timeout=60, charset="UTF-8", autocommit=False,
        tds_version=str(cfg.get("tds_version", "7.4")),   # SQL Server 2012 이상
    )


def query(sql: str, params: tuple | None = None) -> tuple[list[str], list[tuple]]:
    """읽기 쿼리 실행 → (열 이름, 행 목록)"""
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return cols, cur.fetchall()


def explain_error(exc: Exception) -> str:
    """자주 나는 연결 오류를 알기 쉬운 말로"""
    msg = str(exc)
    if "18456" in msg or "Login failed" in msg:
        return "로그인 실패: DB 아이디나 비밀번호가 틀렸습니다. 카페24 관리 화면의 DB 계정 정보를 확인하세요."
    if "4060" in msg or "Cannot open database" in msg:
        return "DB 이름이 틀렸거나 이 계정에 해당 DB 권한이 없습니다."
    if "20002" in msg:
        return ("DB 서버와 접속 절차(TDS)를 시작하지 못했습니다. 가장 흔한 원인은 server 주소가 "
                "홈페이지(웹서버) 주소인 경우입니다. 카페24 '서비스 접속 정보'의 DB 접속 주소"
                "(예: sql19-001.cafe24.com) 또는 ASP 연결 문자열의 Data Source 값을 넣었는지 확인하세요. "
                "아래 '네트워크 진단' 결과도 함께 보세요.")
    if "20009" in msg or "Unable to connect" in msg or "timed out" in msg.lower() or "Adaptive Server is unavailable" in msg:
        return ("서버에 연결할 수 없습니다. 서버 주소·포트를 확인하세요. 주소가 맞다면 카페24가 "
                "외부(특히 해외) 접속을 막고 있을 수 있습니다. 아래 '이 앱의 접속 IP'를 카페24에 알려 허용을 요청하세요.")
    return "알 수 없는 오류입니다. 아래 원본 메시지를 확인하세요."


def diagnose(timeout: int = 8) -> list[tuple[str, str]]:
    """연결 실패 원인 구분용: 주소 → IP 확인, 포트 열림 확인"""
    cfg = settings() or {}
    host, port = cfg.get("server", ""), int(cfg.get("port", 1433))
    out = [("서버 주소", f"{host}:{port}")]
    try:
        ip = socket.gethostbyname(host)
        out.append(("주소 → IP", f"✅ {ip}"))
    except OSError as e:
        out.append(("주소 → IP", f"❌ 주소를 찾을 수 없음 ({e})"))
        return out
    try:
        with socket.create_connection((host, port), timeout=timeout):
            out.append((f"{port} 포트 연결", "✅ 열려 있음 → 네트워크는 정상. 주소가 DB 서버가 맞는지, 계정 정보를 확인하세요."))
    except OSError as e:
        out.append((f"{port} 포트 연결", f"❌ 연결 안 됨 ({e}) → 웹서버 주소이거나, 카페24가 외부/해외 접속을 막고 있음"))
    return out
