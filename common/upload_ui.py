"""화면 공용: 'DB에 업로드' 상자 (관리자 로그인 + DB 설정이 있을 때만 버튼 표시)"""
import pandas as pd
import streamlit as st

from common import auth, db, db_upload


def upload_box(df_or_jobs, target: db_upload.Target | None = None, state_key: str = ""):
    """한 테이블: upload_box(df, target, state_key)
    여러 테이블(한 트랜잭션): upload_box([(df1, target1), (df2, target2)], state_key=...)"""
    jobs = df_or_jobs if isinstance(df_or_jobs, list) else [(df_or_jobs, target)]
    st.divider()
    if not auth.is_admin():
        st.caption("🗄️ DB 업로드는 **관리 > 관리자 로그인** 후 사용할 수 있습니다.")
        return
    if db.settings() is None:
        st.caption("🗄️ DB 접속 정보(Secrets의 [mssql])가 없어 DB 업로드를 할 수 없습니다.")
        return

    prepared, warns = [], []
    for df, tg in jobs:
        rows, w = db_upload.to_records(df, tg)
        prepared.append((tg, rows))
        warns += [f"[{tg.table}] {x}" for x in w] if len(jobs) > 1 else w
    desc = " · ".join(f"`{tg.table}` {len(rows)}행" for tg, rows in prepared)
    c1, c2 = st.columns([3, 1])
    c1.markdown(f"🗄️ **DB 업로드** · {desc}  \n키가 같은 행은 수정, 없으면 추가"
                + (" (모든 테이블을 한 번에 처리)" if len(jobs) > 1 else ""))
    done_key = f"{state_key}_upload"
    if c2.button("DB에 업로드", type="primary", width="stretch", key=f"{state_key}_btn",
                 disabled=not any(rows for _, rows in prepared)):
        try:
            with st.spinner("DB에 반영하는 중..."):
                r = db_upload.upsert_many(prepared)
            msg = " / ".join(f"{t}: 추가 {v['inserted']}행, 수정 {v['updated']}행" for t, v in r.items())
            st.session_state[done_key] = ("ok", f"✅ 업로드 완료 — {msg}")
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
