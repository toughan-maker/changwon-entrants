"""
관리자 로그인 (일반관리자 / 슈퍼관리자)

Secrets:
    [admin]              # 일반관리자: DB 업로드 (관리자들이 함께 사용)
    id = "관리자아이디"
    password = "관리자비밀번호"

    [superadmin]         # 슈퍼관리자: 모든 기능 + DB 연결 테스트 메뉴
    id = "슈퍼관리자아이디"
    password = "슈퍼관리자비밀번호"

- 로그인 상태는 브라우저 세션(st.session_state)에 보관 → 메뉴를 옮겨 다녀도 유지,
  8시간이 지나거나 브라우저 탭을 닫거나 새로고침하면 다시 로그인
- 5번 연속 틀리면 1분 동안 로그인 차단
"""
import hmac
import time

import streamlit as st

SESSION_HOURS = 8
MAX_FAILS, LOCK_SEC = 5, 60
ROLE_NAMES = {"admin": "관리자", "super": "슈퍼관리자"}


def _creds(section: str):
    try:
        a = st.secrets[section]
        return str(a["id"]), str(a["password"])
    except (KeyError, FileNotFoundError):
        return None


def _accounts() -> list[tuple[str, tuple[str, str]]]:
    """(역할, (아이디, 비밀번호)) — 슈퍼관리자를 먼저 확인"""
    out = []
    for role, section in (("super", "superadmin"), ("admin", "admin")):
        c = _creds(section)
        if c:
            out.append((role, c))
    return out


def role() -> str | None:
    """'super' / 'admin' / None(로그인 안 함 또는 시간 만료)"""
    t = st.session_state.get("admin_login_at")
    if t is None:
        return None
    if time.time() - t > SESSION_HOURS * 3600:
        logout()
        return None
    return st.session_state.get("admin_role", "admin")


def is_admin() -> bool:
    """일반관리자 이상 (슈퍼관리자 포함)"""
    return role() is not None


def is_super() -> bool:
    return role() == "super"


def logout():
    for k in ("admin_login_at", "admin_role", "admin_ok"):
        st.session_state.pop(k, None)


def _match(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def login_form(key: str = "admin_login") -> bool:
    """로그인 화면. 로그인 상태면 True, 아니면 폼을 그리고 False"""
    if is_admin():
        return True
    accounts = _accounts()
    if not accounts:
        st.error("관리자 계정(Secrets의 [admin] 또는 [superadmin] id, password)이 설정되지 않았습니다.")
        return False
    locked = st.session_state.get("admin_lock_until", 0) - time.time()
    with st.form(key):
        st.markdown("🔒 **관리자 로그인**")
        uid = st.text_input("아이디")
        pw = st.text_input("비밀번호", type="password")
        ok = st.form_submit_button("로그인", type="primary")
    if ok:
        if locked > 0:
            st.error(f"로그인 시도가 많아 잠시 막혀 있습니다. {int(locked)}초 뒤에 다시 시도하세요.")
            return False
        for r, (cid, cpw) in accounts:
            # 두 값을 모두 비교 (어느 쪽이 틀렸는지 시간 차이로 드러나지 않게)
            if _match(uid, cid) & _match(pw, cpw):
                st.session_state["admin_login_at"] = time.time()
                st.session_state["admin_role"] = r
                st.session_state["admin_fails"] = 0
                st.rerun()
        fails = st.session_state.get("admin_fails", 0) + 1
        st.session_state["admin_fails"] = fails
        if fails >= MAX_FAILS:
            st.session_state["admin_lock_until"] = time.time() + LOCK_SEC
            st.session_state["admin_fails"] = 0
        st.error("아이디 또는 비밀번호가 틀렸습니다.")
    return False


def sidebar_status():
    """사이드바 아래쪽: 로그인 상태 + 로그아웃 버튼"""
    with st.sidebar:
        r = role()
        if r:
            left = SESSION_HOURS * 3600 - (time.time() - st.session_state["admin_login_at"])
            st.caption(f"🔓 {ROLE_NAMES[r]} 로그인 중 (남은 시간 {int(left // 3600)}시간 {int(left % 3600 // 60)}분)")
            if st.button("로그아웃", key="admin_logout"):
                logout()
                st.rerun()
        else:
            st.caption("🔒 DB 업로드·관리는 관리 > 관리자 로그인 후 사용할 수 있습니다.")
