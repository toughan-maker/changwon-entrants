"""
상담결과 관리 (councel) — 관리자·슈퍼관리자 전용
경주일자 + 경기장 + 경주번호로 조회 → 출주표 선수별 상담결과 수정·삭제 (출주표는 바꾸지 않음)
"""
from datetime import date

import streamlit as st

from common import auth, chulju_admin, counsel_admin as A, db
from common.tracks import TRACKS

STATE = "manage_counsel"


def _column_config():
    cfg = {
        "playerNumber": st.column_config.NumberColumn(A.LABEL["playerNumber"], format="%d", disabled=True, width="small"),
        "playerName": st.column_config.TextColumn(A.LABEL["playerName"], disabled=True),
        "_delete": st.column_config.CheckboxColumn("🗑 " + A.LABEL["_delete"], width="small",
                                                   help="체크하고 완료를 누르면 이 선수의 상담결과만 삭제 (출주표는 그대로)"),
    }
    for c in A.EDIT:
        col = A.COLS[c]
        if col.kind == "int":
            cfg[c] = st.column_config.NumberColumn(A.LABEL[c], step=1, format="%d", width="small")
        else:
            cfg[c] = st.column_config.TextColumn(A.LABEL[c], width="large" if c in ("description", "kija_desc") else "medium")
    return cfg


def _load(raceno: str):
    common, df = A.load(raceno)
    ver = st.session_state.get(STATE, {}).get("ver", 0) + 1
    st.session_state[STATE] = {"raceno": raceno, "common": common, "df": df, "ver": ver}


def render():
    st.title("🗣️ 상담결과 관리")
    if not auth.is_admin():          # 메뉴에서 숨겨도 주소로 직접 들어오는 경우 대비
        st.error("관리자 로그인 후 사용할 수 있습니다. (관리 > 관리자 로그인)")
        return
    if db.settings() is None:
        st.error("DB 접속 정보(Secrets의 [mssql])가 없습니다.")
        return
    st.caption("경주를 고르면 그 경주 출전선수의 상담결과를 불러옵니다. 상담결과만 수정·삭제하고 출주표는 바꾸지 않습니다.")

    with st.form("manage_counsel_search"):
        c1, c2, c3 = st.columns(3)
        d = c1.date_input("경주일자", value=date.today(), format="YYYY-MM-DD")
        track = c2.selectbox("경기장", list(TRACKS))
        no = c3.number_input("경주번호", min_value=1, max_value=20, value=1, step=1)
        searched = st.form_submit_button("조회", type="primary", width="stretch")

    msg_key = f"{STATE}_msg"
    if searched:
        st.session_state.pop(msg_key, None)
        prefix = TRACKS[track].prefix
        try:
            raceno = chulju_admin.find_race(prefix, d, int(no))
            if raceno is None:
                st.session_state.pop(STATE, None)
                races = chulju_admin.list_races(prefix, d)
                st.warning(f"{d:%Y-%m-%d} {track} {int(no)}경주 출주표가 DB에 없습니다."
                           + (f" 그날 있는 경주: {', '.join(r[-2:] for r in races)}" if races else " 그날 데이터가 없습니다."))
                return
            _load(raceno)
        except Exception as e:  # noqa: BLE001
            st.error(f"DB 조회 실패: {db.explain_error(e)}\n\n{e}")
            return

    msg = st.session_state.get(msg_key)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])

    s = st.session_state.get(STATE)
    if not s:
        return
    raceno, common, df, ver = s["raceno"], s["common"], s["df"], s["ver"]

    # ── 공통 필드 (표시만)
    cols = st.columns(len(common))
    for col, (k, v) in zip(cols, common.items()):
        col.text_input(k, value=v, disabled=True, key=f"cm_{k}_{raceno}_{ver}")
    no_counsel = int((~df["_has"]).sum())
    st.caption(f"선수 {len(df)}명 · 상담결과 있음 {len(df) - no_counsel}명"
               + (f" · 없음 {no_counsel}명 (값을 입력하고 완료하면 새로 추가됩니다)" if no_counsel else ""))

    # ── 선수별 상담결과 표
    view = df[["playerNumber", "playerName", *A.EDIT, "_delete"]]
    edited = st.data_editor(view, key=f"ed_{raceno}_{ver}", hide_index=True, width="stretch", num_rows="fixed",
                            column_config=_column_config())
    b1, b2 = st.columns([3, 1])
    b1.caption("배번·선수명은 고정. 칸을 눌러 수정하고, 지울 선수는 맨 오른쪽 🗑 삭제를 체크한 뒤 **완료**를 누르세요.")
    if b2.button("✅ 완료 (저장)", type="primary", width="stretch", key=f"save_{raceno}_{ver}"):
        ops, errors = A.plan_save(raceno, df, edited)
        if errors:
            st.error("저장하지 않았습니다. 아래 내용을 고쳐 주세요.\n\n" + "\n".join(f"- {x}" for x in errors))
            return
        if not any(ops.values()):
            st.info("바뀐 내용이 없습니다.")
            return
        try:
            r = A.save(raceno, ops)
        except Exception as e:  # noqa: BLE001
            st.error(f"저장 실패 (모두 취소되어 DB는 바뀌지 않았습니다): {db.explain_error(e)}\n\n{e}")
            return
        _load(raceno)
        st.session_state[msg_key] = ("ok", f"✅ 저장 완료: 수정 {r['update']}명, 추가 {r['insert']}명, 삭제 {r['delete']}명")
        st.rerun()
