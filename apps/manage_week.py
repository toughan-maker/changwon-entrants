"""
짝수 달력 변경 (week_table) — 관리자·슈퍼관리자 전용
"""
from datetime import timedelta

import streamlit as st

from common import auth, db, week_admin as A

STATE = "manage_week"


def _set(df, notes=None, from_db=False):
    ver = st.session_state.get(STATE, {}).get("ver", 0) + 1
    st.session_state[STATE] = {"df": df, "notes": notes or [], "ver": ver, "dirty": not from_db}


def _load():
    df, notes = A.load()
    _set(df, notes, from_db=True)


def render():
    st.title("📅 짝수 달력 변경")
    if not auth.is_admin():          # 메뉴에서 숨겨도 주소로 직접 들어오는 경우 대비
        st.error("관리자 로그인 후 사용할 수 있습니다. (관리 > 관리자 로그인)")
        return
    if db.settings() is None:
        st.error("DB 접속 정보(Secrets의 [mssql])가 없습니다.")
        return

    msg_key = f"{STATE}_msg"
    if STATE not in st.session_state:
        try:
            _load()
        except Exception as e:  # noqa: BLE001
            st.error(f"불러오기 실패: {db.explain_error(e)}\n\n{e}")
            return
    s = st.session_state[STATE]
    for n in s["notes"]:
        st.warning(n)
    msg = st.session_state.pop(msg_key, None)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])
    if s["dirty"]:
        st.info("화면에서 바뀐 내용이 아직 저장되지 않았습니다. **입력**을 눌러야 DB에 저장됩니다.")

    edited = st.data_editor(
        s["df"], key=f"week_{s['ver']}", hide_index=True, num_rows="fixed", width="stretch",
        column_config={
            "week_count": st.column_config.NumberColumn("순서", disabled=True, format="%d", width="small"),
            "start": st.column_config.DateColumn("시작일", format="YYYY-MM-DD"),
            "end": st.column_config.DateColumn("종료일", format="YYYY-MM-DD"),
        })

    # 1번이 빈칸이면 참고용으로 2번 + 7일 안내
    if len(edited) > 1 and A._to_date(edited.iloc[0]["start"]) is None and A._to_date(edited.iloc[1]["start"]):
        s2, e2 = A._to_date(edited.iloc[1]["start"]), A._to_date(edited.iloc[1]["end"]) or A._to_date(edited.iloc[1]["start"])
        st.caption(f"참고: 2번 + 7일 = {s2 + timedelta(days=7)} ~ {e2 + timedelta(days=7)}")

    c1, c2, c3 = st.columns(3)
    if c1.button("⏬ 순서 미루기", width="stretch",
                 help="1→2, 2→3 … 11→12 로 한 칸씩 밀고, 12번 내용은 버리고, 1번은 빈칸으로 둡니다. 입력을 눌러야 저장됩니다."):
        _set(A.shift(edited), s["notes"])
        st.rerun()
    if c2.button("↩ DB에서 다시 불러오기", width="stretch", help="저장하지 않은 변경을 모두 버리고 DB 값으로 되돌립니다."):
        _load()
        st.rerun()
    if c3.button("✅ 입력 (저장)", type="primary", width="stretch"):
        errors, notes = A.check(edited)
        if errors:
            st.error("저장하지 않았습니다.\n\n" + "\n".join(f"- {x}" for x in errors))
            return
        try:
            n = A.save(edited)
        except Exception as e:  # noqa: BLE001
            st.error(f"저장 실패 (모두 취소되어 DB는 바뀌지 않았습니다): {db.explain_error(e)}\n\n{e}")
            return
        _load()
        st.session_state[msg_key] = ("ok", f"✅ 저장 완료: {n}개 순서의 시작일·종료일을 저장했습니다.")
        st.rerun()

    _, notes = A.check(edited)
    for n in notes:
        st.caption("⚠️ " + n)
