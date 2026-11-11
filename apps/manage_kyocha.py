"""
교차경주 관리 (kyocha + tbl_raceorder) — 관리자·슈퍼관리자 전용
"""
import streamlit as st

from common import auth, db, kyocha_admin as A

STATE = "manage_kyocha"


def _load():
    top, raw, order, sample = A.load()
    ver = st.session_state.get(STATE, {}).get("ver", 0) + 1
    st.session_state[STATE] = {"top": top, "raw": raw, "order": order, "sample": sample, "ver": ver}


def render():
    st.title("🔀 교차경주 관리")
    if not auth.is_admin():          # 메뉴에서 숨겨도 주소로 직접 들어오는 경우 대비
        st.error("관리자 로그인 후 사용할 수 있습니다. (관리 > 관리자 로그인)")
        return
    if db.settings() is None:
        st.error("DB 접속 정보(Secrets의 [mssql])가 없습니다.")
        return

    msg_key = f"{STATE}_msg"
    if STATE not in st.session_state or st.button("🔄 DB에서 다시 불러오기"):
        try:
            _load()
        except Exception as e:  # noqa: BLE001
            st.error(f"불러오기 실패: {e if isinstance(e, ValueError) else db.explain_error(e)}")
            return
    s = st.session_state[STATE]
    v = s["ver"]

    msg = st.session_state.get(msg_key)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])

    # ── 상단: kyocha
    t = s["top"]
    grounds = A.GROUNDS if t["kyocha_ground"] in A.GROUNDS else [t["kyocha_ground"], *A.GROUNDS]
    c = st.columns(5)
    top = {
        "kyocha_ground": c[0].selectbox(A.TOP_LABEL["kyocha_ground"], grounds,
                                        index=grounds.index(t["kyocha_ground"]), key=f"kg_{v}"),
        "kyocha_raceno": c[1].number_input(A.TOP_LABEL["kyocha_raceno"], 0, 30, t["kyocha_raceno"], key=f"kr_{v}"),
        "ground_racecount": c[2].number_input(A.TOP_LABEL["ground_racecount"], 0, 30, t["ground_racecount"], key=f"gr_{v}"),
        "kyocha_pageno": c[3].number_input(A.TOP_LABEL["kyocha_pageno"], 0, 999, t["kyocha_pageno"], key=f"kp_{v}"),
        "ground_pageno": c[4].number_input(A.TOP_LABEL["ground_pageno"], 0, 999, t["ground_pageno"], key=f"gp_{v}"),
    }

    # ── 하단: tbl_raceorder
    if st.button("↻ 상단 값으로 다시 만들기",
                 help="교차 경주(교차 경기장 01~) 다음에 광명 경주(잠실 01~) 순서로 표를 새로 채웁니다. 저장은 '입력'을 눌러야 됩니다."):
        st.session_state[STATE]["order"] = A.build_order(top)
        st.session_state[STATE]["ver"] = v = v + 1      # 표를 새 값으로 다시 그리기
        st.session_state[STATE]["top"] = top             # 지금 입력한 상단 값 유지
        st.rerun()
    order = s["order"].copy()
    order["pageno"] = [A.pageno(top, n) for n in order["raceorder"]]
    edited = st.data_editor(
        order, key=f"order_{v}", hide_index=True, num_rows="fixed", width="stretch",
        column_config={
            "raceorder": st.column_config.NumberColumn("경주순서", disabled=True, format="%d"),
            "ground": st.column_config.SelectboxColumn("경기장", options=sorted(set(A.GROUNDS) | set(order["ground"])),
                                                       required=True),
            "racecount": st.column_config.TextColumn("경주번호", max_chars=4, required=True),
            "pageno": st.column_config.NumberColumn("페이지번호 (자동)", disabled=True, format="%d"),
        })
    st.caption("페이지번호 = 교차1경주 짝수페이지번호 + 2 × (경주순서 − 1). 상단 값을 바꾸면 바로 다시 계산됩니다.")

    errors, notes = A.check(top, edited)
    for n in notes:
        st.info(n)
    if st.button("✅ 입력 (저장)", type="primary", width="stretch", key=f"save_{v}"):
        if errors:
            st.error("저장하지 않았습니다.\n\n" + "\n".join(f"- {x}" for x in errors))
            return
        try:
            r = A.save(top, s["raw"], edited[["raceorder", "ground", "racecount"]], s["sample"])
        except Exception as e:  # noqa: BLE001
            st.error(f"저장 실패 (모두 취소되어 DB는 바뀌지 않았습니다): {db.explain_error(e)}\n\n{e}")
            return
        _load()
        st.session_state[msg_key] = ("ok", f"✅ 저장 완료: 교차경주 설정 수정, 순서표 수정 {r['update']}줄 · 추가 {r['insert']}줄 · 삭제 {r['delete']}줄")
        st.rerun()
