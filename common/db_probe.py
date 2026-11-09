"""
DB 접속 방식 진단 (관리자 연결 테스트용)

1) probe_server: SQL Server 에 첫 인사(PRELOGIN)만 보내서 버전과 암호화 설정을 읽음 (로그인 안 함)
2) try_modes:   접속 방식(드라이버·암호화 설정)을 하나씩 '별도 프로세스'에서 시도
                → 서로 설정이 섞이지 않고, 어느 방식이 되는지 표로 확인

접속 방식 (secrets 의 [mssql] mode 값으로 고정 가능)
    default : pymssql 기본 (최신 TLS만 허용)
    legacy  : pymssql + 옛 TLS(1.0/1.1)·옛 암호 허용  ← 오래된 SQL Server 용
    pytds   : python-tds, 암호화 없이 접속 (서버가 암호화를 강제하지 않을 때만)
"""
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile

MODES = {
    "default": "pymssql 기본",
    "legacy": "pymssql + 옛 TLS 허용",
    "legacy_off": "pymssql + 옛 TLS 허용 + 로그인만 암호화",
    "pytds": "python-tds (암호화 없음)",
}

_FREETDS_CONF = "[global]\n    enable tls v1 = yes\n"
_OPENSSL_CONF = """openssl_conf = openssl_init
[openssl_init]
ssl_conf = ssl_sect
[ssl_sect]
system_default = system_default_sect
[system_default_sect]
MinProtocol = TLSv1
CipherString = DEFAULT@SECLEVEL=0
"""


def legacy_env() -> dict:
    """옛 TLS 허용용 환경변수 (pymssql 에 들어있는 FreeTDS·OpenSSL 에만 적용)"""
    d = os.path.join(tempfile.gettempdir(), "mssql_legacy")
    os.makedirs(d, exist_ok=True)
    paths = {}
    for name, text in (("freetds.conf", _FREETDS_CONF), ("openssl.cnf", _OPENSSL_CONF)):
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write(text)
        paths[name] = p
    return {"FREETDSCONF": paths["freetds.conf"], "OPENSSL_CONF": paths["openssl.cnf"]}


# ───────────────────────── 1) 서버 첫 인사 ─────────────────────────
_ENC = {0: "OFF (로그인만 암호화)", 1: "ON (암호화 사용)", 2: "NOT_SUP (암호화 미지원)", 3: "REQ (암호화 필수)"}
_VER = {8: "2000", 9: "2005", 10: "2008/2008 R2", 11: "2012", 12: "2014", 13: "2016", 14: "2017",
        15: "2019", 16: "2022"}


def probe_server(host: str, port: int, timeout: int = 8) -> dict:
    """PRELOGIN 패킷으로 서버 버전·암호화 설정 확인. 로그인은 하지 않음."""
    # 옵션: VERSION(0), ENCRYPTION(1) → 데이터: 버전 6바이트 + 암호화 1바이트(ENCRYPT_NOT_SUP=2)
    header_len = 5 * 2 + 1
    opts = struct.pack(">BHH", 0, header_len, 6) + struct.pack(">BHH", 1, header_len + 6, 1) + b"\xff"
    data = struct.pack(">IH", 0, 0) + b"\x02"
    payload = opts + data
    packet = struct.pack(">BBHHBB", 0x12, 1, 8 + len(payload), 0, 0, 0) + payload
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(packet)
        resp = s.recv(4096)
    if len(resp) < 8 or resp[0] != 0x04:
        return {"error": f"SQL Server 응답이 아닙니다 (첫 바이트 {resp[:1].hex() or '없음'})"}
    body, out, i = resp[8:], {}, 0
    while i < len(body) and body[i] != 0xFF:
        tok, off, ln = struct.unpack(">BHH", body[i:i + 5])
        val = body[off:off + ln]
        if tok == 0 and len(val) >= 4:
            major, minor, build = val[0], val[1], struct.unpack(">H", val[2:4])[0]
            out["버전"] = f"{major}.{minor}.{build} (SQL Server {_VER.get(major, '?')})"
            out["major"] = major
        elif tok == 1 and val:
            out["암호화 설정"] = _ENC.get(val[0], str(val[0]))
            out["enc"] = val[0]
        i += 5
    return out


# ───────────────────────── 2) 접속 방식 시도 ─────────────────────────
_CHILD = r'''
import json, sys
cfg = json.loads(sys.stdin.read())
mode = cfg["mode"]
try:
    if mode == "pytds":
        import pytds
        conn = pytds.connect(server=cfg["server"], port=int(cfg["port"]), database=cfg["database"],
                             user=cfg["user"], password=cfg["password"], login_timeout=15, timeout=30)
    else:
        import pymssql
        kw = dict(server=cfg["server"], port=str(cfg["port"]), user=cfg["user"], password=cfg["password"],
                  database=cfg["database"], login_timeout=15, timeout=30, tds_version="7.4")
        if mode == "legacy_off":
            kw["encryption"] = "off"
        conn = pymssql.connect(**kw)
    cur = conn.cursor()
    cur.execute("SELECT CAST(SERVERPROPERTY('ProductVersion') AS varchar(30)), DB_NAME()")
    row = cur.fetchone()
    conn.close()
    print(json.dumps({"ok": True, "msg": f"접속 성공 (버전 {row[0]}, DB {row[1]})"}))
except Exception as e:
    print(json.dumps({"ok": False, "msg": f"{type(e).__name__}: {e}"[:400]}))
'''


def try_mode(cfg: dict, mode: str, timeout: int = 40) -> dict:
    env = dict(os.environ)
    if mode.startswith("legacy"):
        env.update(legacy_env())
    arg = json.dumps({**{k: cfg.get(k) for k in ("server", "database", "user", "password")},
                      "port": cfg.get("port", 1433), "mode": mode})
    try:
        r = subprocess.run([sys.executable, "-c", _CHILD], input=arg, capture_output=True, text=True,
                           timeout=timeout, env=env)
        line = (r.stdout.strip().splitlines() or [""])[-1]
        return json.loads(line) if line.startswith("{") else {"ok": False, "msg": (r.stderr or "응답 없음")[-400:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "msg": "시간 초과"}
