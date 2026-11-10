"""화면 공용: 'DB에 업로드' 상자 (관리자 로그인 + DB 설정이 있을 때만 버튼 표시)"""
import pandas as pd
import streamlit as st

from common import auth, db, db_upload


def upload_box(df: pd.DataFrame, target: db_upload.Target, state_key: str):
    st.divider()
    if not auth.is_admin():
        st.caption("🗄️ DB 업로드는 **관리 > 관리자 로그인** 후 사용할 수 있습니다.")
        return
    if db.settings() is None:
        st.caption("🗄️ DB 접속 정보(Secrets의 [mssql])가 없어 DB 업로드를 할 수 없습니다.")
        return
    rows, warns = db_upload.to_records(df, target)
    keys = " + ".join(target.keys)
    c1, c2 = st.columns([3, 1])
    c1.markdown(f"🗄️ **DB 업로드** · `{target.table}` 에 {len(rows)}행 ({keys} 가 같으면 수정, 없으면 추가)")
    done_key = f"{state_key}_upload"
    if c2.button("DB에 업로드", type="primary", width="stretch", key=f"{state_key}_btn", disabled=not rows):
        try:
            with st.spinner("DB에 반영하는 중..."):
                r = db_upload.upsert(target, rows)
            st.session_state[done_key] = ("ok", f"✅ 업로드 완료: 추가 {r['inserted']}행, 수정 {r['updated']}행")
        except Exception as e:  # noqa: BLE001
            st.session_state[done_key] = (
                "err", f"업로드 실패 (모두 취소되어 DB는 바뀌지 않았습니다): {db.explain_error(e)}\n\n{e}")
    if warns:
        with st.expander(f"⚠️ 업로드 주의 {len(warns)}건", expanded=len(warns) <= 5):
            for w in warns:
                st.write("- " + w)
    done = st.session_state.get(done_key)
    if done:
        (st.success if done[0] == "ok" else st.error)(done[1])
