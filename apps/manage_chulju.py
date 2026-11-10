"""
출주표 관리 (chuljuRec) — 관리자·슈퍼관리자 전용
경주일자 + 경기장 + 경주번호로 조회 → 공통 필드·선수 표 수정 → 완료(저장) / 경주 삭제
"""
from datetime import date

import streamlit as st

from common import auth, chulju_admin as A, db
from common.tracks import TRACKS

STATE = "manage_chulju"


def _column_config():
    """표 머리는 한글 이름만. 선수번호는 키라서 수정 불가"""
    cfg = {}
    for c in A.GRID:
        col, label = A.COLS[c], A.LABEL[c]
        if col.kind == "int":
            cfg[c] = st.column_config.NumberColumn(label, step=1, format="%d", disabled=(c == "playerNumber"))
        elif col.kind == "float":
            cfg[c] = st.column_config.NumberColumn(label, format="%.2f")
        else:
            cfg[c] = st.column_config.TextColumn(label, max_chars=col.size)
    return cfg


def _load(raceno: str):
    common, grid = A.load_race(raceno)
    ver = st.session_state.get(STATE, {}).get("ver", 0) + 1
    st.session_state[STATE] = {"raceno": raceno, "common": common, "grid": grid, "ver": ver}


def render():
    st.title("📝 출주표 관리")
    if not auth.is_admin():          # 메뉴에서 숨겨도 주소로 직접 들어오는 경우 대비
        st.error("관리자 로그인 후 사용할 수 있습니다. (관리 > 관리자 로그인)")
        return
    if db.settings() is None:
        st.error("DB 접속 정보(Secrets의 [mssql])가 없습니다.")
        return
    st.caption("DB에 올라간 출주표를 경주별로 불러와 수정하거나 삭제합니다.")

    with st.form("manage_chulju_search"):
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
            raceno = A.find_race(prefix, d, int(no))
            if raceno is None:
                st.session_state.pop(STATE, None)
                races = A.list_races(prefix, d)
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
    raceno, common, grid, ver = s["raceno"], s["common"], s["grid"], s["ver"]
    k = f"{raceno}_{ver}"

    # ── 공통 필드 + 삭제 버튼
    st.subheader(f"{raceno} · 선수 {len(grid)}명")
    c = st.columns([2, 2, 1.5, 1.5, 1.5, 1.2], vertical_alignment="bottom")
    c[0].text_input("경주번호", value=raceno, disabled=True, key=f"rn_{k}")
    new_common = {
        "playDate": c[1].date_input("경주일", value=common.get("playDate"), format="YYYY-MM-DD", key=f"pd_{k}"),
        "playTime": c[2].text_input("경주시간", value=common.get("playTime", ""), max_chars=10, key=f"pt_{k}"),
        "ground": c[3].text_input("경기장", value=common.get("ground", ""), max_chars=10, key=f"gr_{k}"),
        "grade": c[4].text_input("등급", value=common.get("grade", ""), max_chars=10, key=f"gd_{k}"),
    }
    with c[5].popover("🗑 삭제", width="stretch"):
        st.warning(f"**{raceno}** 의 {len(grid)}행을 모두 삭제합니다. 되돌릴 수 없습니다.")
        if st.button("삭제 확인", type="primary", key=f"del_{k}"):
            try:
                n = A.delete_race(raceno)
                st.session_state.pop(STATE, None)
                st.session_state[msg_key] = ("ok", f"🗑 {raceno} 의 {n}행을 삭제했습니다.")
            except Exception as e:  # noqa: BLE001
                st.session_state[msg_key] = ("err", f"삭제 실패 (DB는 바뀌지 않았습니다): {db.explain_error(e)}\n\n{e}")
            st.rerun()

    # ── 선수 표
    st.caption("칸을 눌러 바로 고칠 수 있습니다 (선수번호는 고정). 행 왼쪽을 선택하고 휴지통 아이콘을 누르면 선수 삭제. "
               "고친 뒤 **완료**를 눌러야 저장됩니다.")
    edited = st.data_editor(grid, key=f"ed_{k}", num_rows="delete", hide_index=True, width="stretch",
                            column_config=_column_config(), column_order=A.GRID)

    b1, b2 = st.columns([3, 1])
    if b2.button("✅ 완료 (저장)", type="primary", width="stretch", key=f"save_{k}"):
        ops, errors = A.plan_save(raceno, common, new_common, grid, edited)
        if errors:
            st.error("저장하지 않았습니다. 아래 내용을 고쳐 주세요.\n\n" + "\n".join(f"- {x}" for x in errors))
            return
        if not (ops["update"] or ops["insert"] or ops["delete"]):
            st.info("바뀐 내용이 없습니다.")
            return
        try:
            r = A.save(raceno, ops)
        except Exception as e:  # noqa: BLE001
            st.error(f"저장 실패 (모두 취소되어 DB는 바뀌지 않았습니다): {db.explain_error(e)}\n\n{e}")
            return
        _load(raceno)   # 저장된 값으로 다시 불러오기
        st.session_state[msg_key] = ("ok", f"✅ 저장 완료: 수정 {r['update']}행, 삭제 {r['delete']}행")
        st.rerun()
    b1.caption("완료를 누르면 바뀐 행만 저장합니다. 공통 필드를 바꾸면 이 경주의 모든 행에 적용됩니다.")
