"""
관리자 로그인 (ID/비밀번호 1개를 관리자들이 함께 사용)

Secrets:
    [admin]
    id = "관리자아이디"
    password = "관리자비밀번호"

- 로그인 상태는 브라우저 세션(st.session_state)에 보관 → 메뉴를 옮겨 다녀도 유지,
  8시간이 지나거나 브라우저 탭을 닫거나 새로고침하면 다시 로그인
- 5번 연속 틀리면 1분 동안 로그인 차단
"""
import hmac
import time

import streamlit as st

SESSION_HOURS = 8
MAX_FAILS, LOCK_SEC = 5, 60


def _creds():
    try:
        a = st.secrets["admin"]
        return str(a.get("id", "admin")), str(a["password"])
    except (KeyError, FileNotFoundError):
        return None


def is_admin() -> bool:
    t = st.session_state.get("admin_login_at")
    if t is None:
        return False
    if time.time() - t > SESSION_HOURS * 3600:
        logout()
        return False
    return True


def logout():
    for k in ("admin_login_at", "admin_ok"):
        st.session_state.pop(k, None)


def login_form(key: str = "admin_login") -> bool:
    """로그인 화면. 로그인 상태면 True, 아니면 폼을 그리고 False"""
    if is_admin():
        return True
    creds = _creds()
    if creds is None:
        st.error("관리자 계정(Secrets의 [admin] id, password)이 설정되지 않았습니다.")
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
        if hmac.compare_digest(uid.encode(), creds[0].encode()) and hmac.compare_digest(pw.encode(), creds[1].encode()):
            st.session_state["admin_login_at"] = time.time()
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
        if is_admin():
            left = SESSION_HOURS * 3600 - (time.time() - st.session_state["admin_login_at"])
            st.caption(f"🔓 관리자 로그인 중 (남은 시간 {int(left // 3600)}시간 {int(left % 3600 // 60)}분)")
            if st.button("로그아웃", key="admin_logout"):
                logout()
                st.rerun()
        else:
            st.caption("🔒 DB 업로드·관리는 관리 > 관리자 로그인 후 사용할 수 있습니다.")
