"""
DB 연결 테스트 (관리자 전용)
- 읽기 전용: 서버 정보, 테이블 목록, 테이블 열 구조만 조회합니다. 데이터는 바꾸지 않습니다.
- 임시 잠금: Secrets 의 [admin] password 로 확인 (정식 로그인은 다음 단계에서 추가)
"""
import hmac

import pandas as pd
import requests
import streamlit as st

from common import db, db_probe


def _admin_gate() -> bool:
    """임시 관리자 확인. 통과하면 True"""
    try:
        admin_pw = st.secrets["admin"]["password"]
    except (KeyError, FileNotFoundError):
        st.error("관리자 비밀번호(Secrets의 [admin] password)가 설정되지 않아 이 화면을 열 수 없습니다.")
        return False
    if st.session_state.get("admin_ok"):
        return True
    with st.form("admin_login"):
        pw = st.text_input("관리자 비밀번호", type="password")
        if st.form_submit_button("확인", type="primary"):
            if hmac.compare_digest(pw.encode(), str(admin_pw).encode()):
                st.session_state["admin_ok"] = True
                st.rerun()
            st.error("비밀번호가 틀렸습니다.")
    return False


@st.cache_data(ttl=3600, show_spinner=False)
def _my_ip() -> str:
    """이 앱이 밖으로 나갈 때 쓰는 IP (카페24에 허용 요청할 때 필요)"""
    try:
        return requests.get("https://api.ipify.org", timeout=10).text.strip()
    except requests.RequestException:
        return "확인 실패"


def _mode_check(cfg: dict):
    """서버 버전·암호화 설정 확인 + 접속 방식별 시도"""
    if not st.button("접속 방식 진단", width="stretch", key="mode_check"):
        return
    host, port = cfg["server"], int(cfg.get("port", 1433))
    with st.spinner("서버 정보 확인 중..."):
        try:
            info = db_probe.probe_server(host, port)
        except OSError as e:
            info = {"error": str(e)}
    st.markdown("**서버 정보 (로그인 전 확인)**")
    st.table(pd.DataFrame([(k, v) for k, v in info.items() if k not in ("major", "enc")],
                          columns=["항목", "결과"]).set_index("항목"))

    rows, ok_modes = [], []
    with st.spinner("접속 방식을 하나씩 시도하는 중... (최대 2~3분)"):
        for m, label in db_probe.MODES.items():
            r = db_probe.try_mode(cfg, m)
            rows.append((m, label, "✅ 성공" if r["ok"] else "❌ 실패", r["msg"]))
            if r["ok"]:
                ok_modes.append(m)
    st.markdown("**접속 방식별 결과**")
    st.dataframe(pd.DataFrame(rows, columns=["mode", "방식", "결과", "내용"]), hide_index=True, width="stretch")
    if ok_modes:
        best = ok_modes[0]
        st.success(f"'{best}' 방식으로 접속됩니다. Secrets의 [mssql]에 mode = \"{best}\" 를 추가하고 앱을 재시작하세요.")
        if best == "pytds":
            st.warning("pytds 방식은 암호화 없이 접속합니다. 가능하면 카페24에 SQL Server TLS 1.2 지원 여부를 문의해 보세요.")
    else:
        st.error("모든 방식이 실패했습니다. 이 표 전체를 알려주세요.")


def render():
    st.title("🔌 DB 연결 테스트")
    st.caption("카페24 MSSQL에 접속되는지 확인합니다. 읽기만 하고 데이터는 바꾸지 않습니다.")
    if not _admin_gate():
        return

    cfg = db.settings()
    c1, c2 = st.columns(2)
    c1.metric("이 앱의 접속 IP", _my_ip())
    c2.metric("설정된 DB 서버", f"{cfg['server']}:{cfg.get('port', 1433)}" if cfg else "미설정")
    if cfg is None:
        st.warning("Secrets에 [mssql] 접속 정보가 없습니다. 안내에 따라 server, database, user, password를 넣어 주세요.")
        return
    st.caption(f"DB: {cfg['database']} · 계정: {cfg['user']} · 접속 방식: {db.mode()} ({db_probe.MODES[db.mode()]})")

    if st.button("연결 테스트", type="primary", width="stretch"):
        try:
            with st.spinner("접속 중..."):
                cols, rows = db.query(
                    "SELECT @@SERVERNAME AS 서버, DB_NAME() AS DB, SUSER_SNAME() AS 계정, "
                    "CONVERT(varchar(19), GETDATE(), 120) AS 서버시각, "
                    "CAST(SERVERPROPERTY('ProductVersion') AS varchar(30)) AS 버전")
                tcols, trows = db.query(
                    "SELECT TABLE_SCHEMA AS 스키마, TABLE_NAME AS 테이블, TABLE_TYPE AS 종류 "
                    "FROM INFORMATION_SCHEMA.TABLES ORDER BY TABLE_NAME")
        except Exception as e:  # noqa: BLE001 — 어떤 오류든 화면에 설명
            st.session_state.pop("db_tables", None)
            st.error(db.explain_error(e))
            with st.spinner("네트워크 진단 중..."):
                diag = db.diagnose()
            st.markdown("**네트워크 진단**")
            st.table(pd.DataFrame(diag, columns=["항목", "결과"]).set_index("항목"))
            with st.expander("원본 오류 메시지"):
                st.code(str(e), language=None)
            st.info("포트가 열려 있다면 아래 '접속 방식 진단'을 눌러 되는 방식을 찾아 주세요.")
            st.session_state["db_failed"] = True
        else:
            st.session_state["db_failed"] = False
            st.success("✅ 연결 성공")
            st.dataframe(pd.DataFrame(rows, columns=cols), hide_index=True, width="stretch")
            st.session_state["db_tables"] = pd.DataFrame(trows, columns=tcols)

    with st.expander("🔧 접속 방식 진단 (연결이 안 될 때)", expanded=bool(st.session_state.get("db_failed"))):
        st.caption("서버 버전·암호화 설정을 확인하고, 접속 방식을 하나씩 시도해 되는 방식을 찾습니다. 데이터는 바꾸지 않습니다.")
        _mode_check(cfg)

    tables = st.session_state.get("db_tables")
    if tables is None:
        return
    st.subheader(f"테이블 목록 ({len(tables)}개)")
    st.dataframe(tables, hide_index=True, width="stretch")

    name = st.selectbox("열 구조를 볼 테이블", tables["테이블"].tolist(), index=None,
                        placeholder="테이블을 고르세요")
    if name:
        schema = tables.loc[tables["테이블"] == name, "스키마"].iloc[0]
        cols, rows = db.query(
            "SELECT c.COLUMN_NAME AS 열, c.DATA_TYPE AS 형식, "
            "COALESCE(CAST(c.CHARACTER_MAXIMUM_LENGTH AS varchar(10)), "
            "         CAST(c.NUMERIC_PRECISION AS varchar(10)) + ',' + CAST(c.NUMERIC_SCALE AS varchar(10))) AS 크기, "
            "c.IS_NULLABLE AS NULL허용, "
            "CASE WHEN k.COLUMN_NAME IS NULL THEN '' ELSE 'PK' END AS 기본키 "
            "FROM INFORMATION_SCHEMA.COLUMNS c "
            "LEFT JOIN (SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME "
            "           FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
            "           JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku "
            "             ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME AND tc.TABLE_SCHEMA = ku.TABLE_SCHEMA "
            "           WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY') k "
            "  ON k.TABLE_SCHEMA = c.TABLE_SCHEMA AND k.TABLE_NAME = c.TABLE_NAME AND k.COLUMN_NAME = c.COLUMN_NAME "
            "WHERE c.TABLE_SCHEMA = %s AND c.TABLE_NAME = %s ORDER BY c.ORDINAL_POSITION",
            (schema, name))
        df = pd.DataFrame(rows, columns=cols)
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption("이 표를 복사해서 보내주시면 업로드 기능을 테이블 구조에 맞춰 만들 수 있습니다.")
        # 탭 구분 (엑셀에 붙여넣기 좋고, '10,0' 같은 크기 값과 섞이지 않음)
        st.code("\n".join("\t".join(str(v) for v in r) for r in [cols] + [list(x) for x in rows]), language=None)
