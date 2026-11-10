"""관리자 로그인 화면"""
import streamlit as st

from common import auth


def render():
    st.title("🔑 관리자 로그인")
    if not auth.login_form():
        st.caption("로그인하면 출주표 화면의 DB 업로드, 관리 메뉴를 사용할 수 있습니다. "
                   f"로그인은 {auth.SESSION_HOURS}시간 유지되며, 새로고침하거나 탭을 닫으면 다시 로그인해야 합니다.")
        return
    st.success(f"{auth.ROLE_NAMES[auth.role()]}로 로그인되어 있습니다.")
    if auth.is_super():
        st.caption("슈퍼관리자: 모든 기능 + 관리 > DB 연결 테스트")
    else:
        st.caption("관리자: 출주표·상담결과·경주결과 화면의 DB 업로드")
    if st.button("로그아웃"):
        auth.logout()
        st.rerun()
