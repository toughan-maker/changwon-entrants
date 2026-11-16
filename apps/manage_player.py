"""
선수정보 관리 (player_info) — 관리자·슈퍼관리자 전용
선수조회 → 목록에서 선수 선택 → 상세정보 수정 / 삭제, 새 선수 추가
"""
from datetime import date

import streamlit as st

from common import auth, db, player_admin as A, site_kcycle

STATE = "manage_player"
SECTIONS = ["기본", "기록·등급", "학력·경력", "능력치", "친분 선수"]


def _st() -> dict:
    return st.session_state.setdefault(STATE, {"ver": 0})


def _bump():
    _st()["ver"] += 1


def _input(f: A.F, value, key: str):
    """필드 형식에 맞는 입력칸"""
    label = f.label + (" *" if f.required else "")
    if f.kind in A.RANGE:
        lo, hi = A.RANGE[f.kind]
        return st.number_input(label, min_value=lo, max_value=hi, value=None if value is None else int(value),
                               step=1, key=key)
    if f.kind == "date":
        return st.date_input(label, value=value, min_value=date(1940, 1, 1), max_value=date.today(),
                             format="YYYY-MM-DD", key=key)
    if f.wide or f.kind == "text":
        return st.text_area(label, value=value or "", key=key, height=100)
    return st.text_input(label, value=value or "", key=key)


def _form(info: dict, retire_col: bool, new: bool, key: str):
    """상세 입력 폼 → (제출 여부, 입력 값)"""
    vals = {}
    with st.form(f"player_form_{key}"):
        for sec in SECTIONS:
            fields = [f for f in A.INFO_FIELDS if f.section == sec]
            st.markdown(f"**{sec}**")
            normal = [f for f in fields if not (f.wide or f.kind == "text")]
            cols = st.columns(4)
            for i, f in enumerate(normal):
                with cols[i % 4]:
                    if f.db == "playerName" and not new:
                        st.text_input("선수명", value=info.get("playerName", ""), disabled=True, key=f"pn_{key}")
                        continue
                    vals[f.db] = _input(f, info.get(f.db), f"{f.db}_{sec}_{key}")
            if sec == "기본" and retire_col:
                with cols[len(normal) % 4]:
                    cur = "은퇴" if str(info.get("retire_yn", "n")).lower() == "y" else "현역"
                    vals["retire_yn"] = "y" if st.selectbox("현역여부", ["현역", "은퇴"], index=["현역", "은퇴"].index(cur),
                                                            key=f"ret_{key}") == "은퇴" else "n"
            for f in fields:
                if f.wide or f.kind == "text":
                    vals[f.db] = _input(f, info.get(f.db), f"{f.db}_{key}")
            st.divider()
        st.caption("* 표시는 꼭 입력해야 하는 항목입니다. 글자 길이는 바이트 기준입니다 (한글 1자 = 2바이트).")
        ok = st.form_submit_button("➕ 선수 추가" if new else "✅ 저장", type="primary", width="stretch")
    return ok, vals


def _retire_setup(retire_col: bool):
    if retire_col:
        return
    st.warning("player_info 에 은퇴여부(retire_yn) 열이 아직 없습니다. 지금은 모든 선수를 현역으로 표시하고, 현역/은퇴 검색은 쓸 수 없습니다.")
    if not auth.is_super():
        st.caption("슈퍼관리자가 이 화면에서 열을 추가할 수 있습니다.")
        return
    c1, c2 = st.columns([1, 2])
    with c1.popover("은퇴여부 열 추가 (슈퍼관리자)"):
        st.markdown("player_info 에 `retire_yn char(1)` 열을 기본값 `'n'` 으로 추가합니다. 기존 선수는 모두 `n`(현역)이 됩니다.")
        if st.button("열 추가 실행", type="primary", key="add_retire"):
            try:
                A.add_retire_column()
                _st().pop("retire_col", None)
                st.session_state[f"{STATE}_msg"] = ("ok", "✅ retire_yn 열을 추가했습니다. 기존 선수는 모두 현역(n)입니다.")
            except Exception as e:  # noqa: BLE001
                st.session_state[f"{STATE}_msg"] = ("err", f"열 추가 실패 (DB 계정에 ALTER 권한이 없을 수 있습니다): {e}")
            st.rerun()
    with c2.expander("SSMS에서 직접 실행할 SQL"):
        st.code(A.ADD_RETIRE_SQL + ";", language="sql")


def _retire_sync(retire_col: bool):
    """KCYCLE 선수조회(현역/은퇴 명단)를 보고 은퇴 선수의 retire_yn 을 y 로"""
    with st.expander("🔄 KCYCLE 은퇴 명단 반영", expanded=bool(_st().get("sync"))):
        if not retire_col:
            st.info("은퇴여부(retire_yn) 열을 먼저 추가해야 쓸 수 있습니다.")
            return
        st.caption("kcycle.or.kr 선수조회의 현역·은퇴 명단을 가져와 선수번호(reg_code)로 비교합니다. "
                   "확인 버튼을 누르기 전에는 DB를 바꾸지 않습니다.")
        if st.button("명단 가져와서 비교", key="sync_fetch"):
            try:
                with st.spinner("KCYCLE 명단을 가져오는 중…"):
                    retired, active = site_kcycle.racer_list(True), site_kcycle.racer_list(False)
                if retired.empty or active.empty:
                    st.error("KCYCLE 명단을 읽지 못했습니다. 사이트 구조가 바뀌었을 수 있습니다.")
                    return
                _st()["sync"] = A.retire_plan(retired, active)
            except Exception as e:  # noqa: BLE001
                st.error(f"비교 실패: {db.explain_error(e)}\n\n{e}")
                return
        plan = _st().get("sync")
        if not plan:
            return
        st.write(" · ".join(f"{k} {v}명" for k, v in plan["counts"].items()))
        to_y = plan["to_y"]
        if to_y.empty:
            st.success("새로 은퇴로 바꿀 선수가 없습니다.")
        else:
            st.markdown(f"**은퇴(y)로 바꿀 선수 {len(to_y)}명**")
            st.dataframe(to_y[["선수번호", "선수명", "기수", "KCYCLE 이름"]], hide_index=True, width="stretch",
                         height=min(400, 38 + 35 * len(to_y)))
            if st.button(f"✅ {len(to_y)}명 은퇴로 변경", type="primary", key="sync_apply"):
                try:
                    n = A.set_retired(to_y["선수번호"].tolist(), "y")
                except Exception as e:  # noqa: BLE001
                    st.error(f"변경 실패 (DB는 바뀌지 않았습니다): {db.explain_error(e)}\n\n{e}")
                    return
                _st().pop("sync", None)
                st.session_state[f"{STATE}_msg"] = ("ok", f"✅ {n}명을 은퇴(y)로 바꿨습니다.")
                st.rerun()
        for key, title, note in [
            ("back", "DB는 은퇴인데 KCYCLE에서는 현역인 선수", "자동으로 바꾸지 않습니다. 필요하면 상세정보에서 직접 고치세요."),
            ("name_diff", "선수번호는 같은데 이름 표기가 다른 선수", "참고용입니다."),
            ("unknown", "KCYCLE 명단 어디에도 없는 선수번호", "선수번호(reg_code)가 비었거나 다르게 들어간 경우입니다."),
        ]:
            df = plan[key]
            if not df.empty:
                with st.popover(f"{title} {len(df)}명"):
                    st.caption(note)
                    st.dataframe(df, hide_index=True, width="stretch")


def render():
    st.title("🏃 선수정보 관리")
    if not auth.is_admin():          # 메뉴에서 숨겨도 주소로 직접 들어오는 경우 대비
        st.error("관리자 로그인 후 사용할 수 있습니다. (관리 > 관리자 로그인)")
        return
    if db.settings() is None:
        st.error("DB 접속 정보(Secrets의 [mssql])가 없습니다.")
        return
    s = _st()
    try:
        if "retire_col" not in s:
            s["retire_col"] = A.has_retire()
        if "opts" not in s:
            s["opts"] = A.options()
    except Exception as e:  # noqa: BLE001
        st.error(f"DB 조회 실패: {db.explain_error(e)}\n\n{e}")
        return
    retire_col = s["retire_col"]
    kisus = s["opts"]

    msg = st.session_state.pop(f"{STATE}_msg", None)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])
    _retire_setup(retire_col)
    _retire_sync(retire_col)

    # ── 선수조회
    with st.form("player_search"):
        c = st.columns([1, 1, 1, 2])
        status = c[0].selectbox("현역/은퇴", ["전체", "현역", "은퇴"], index=1, disabled=not retire_col)
        grade = c[1].selectbox("등급", ["전체", *A.GRADE_GROUPS], format_func=lambda g: A.GRADE_GROUPS.get(g, g))
        kisu = c[2].selectbox("기수", ["전체", *kisus], format_func=lambda k: k if k == "전체" else f"{k}기")
        name = c[3].text_input("선수명", placeholder="일부만 입력해도 됩니다")
        searched = st.form_submit_button("검색", type="primary", width="stretch")
    if st.button("➕ 새 선수 추가"):
        s.update(mode="new", selected=None); _bump()
    if searched:
        try:
            s["results"] = A.search(status, None if grade == "전체" else grade, None if kisu == "전체" else kisu,
                                    name, retire_col)
        except Exception as e:  # noqa: BLE001
            st.error(f"검색 실패: {db.explain_error(e)}\n\n{e}")
            return
        s.update(mode=None, selected=None); _bump()

    res = s.get("results")
    if res is not None:
        st.caption(f"총 {len(res)}명 · 행을 누르면 아래에 상세정보가 나옵니다.")
        ev = st.dataframe(res, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                          key=f"plist_{s['ver']}", height=min(400, 38 + 35 * max(len(res), 1)))
        rows = ev.selection.rows if ev and ev.selection else []
        if rows:
            picked = res.iloc[rows[0]]["선수명"]
            if s.get("selected") != picked or s.get("mode") != "detail":
                s.update(mode="detail", selected=picked)

    # ── 새 선수 추가
    if s.get("mode") == "new":
        st.subheader("➕ 새 선수 추가")
        ok, vals = _form({}, retire_col, True, f"new_{s['ver']}")
        if ok:
            try:
                errors = A.create(vals, retire_col)
            except Exception as e:  # noqa: BLE001
                st.error(f"추가 실패 (DB는 바뀌지 않았습니다): {db.explain_error(e)}\n\n{e}")
                return
            if errors:
                st.error("추가하지 않았습니다.\n\n" + "\n".join(f"- {x}" for x in errors))
                return
            s.update(mode="detail", selected=vals["playerName"].strip(), opts=A.options())
            st.session_state[f"{STATE}_msg"] = ("ok", f"✅ '{vals['playerName'].strip()}' 선수를 추가했습니다.")
            st.rerun()

    # ── 상세정보
    if s.get("mode") == "detail" and s.get("selected"):
        pname = s["selected"]
        try:
            info = A.load(pname, retire_col)
        except Exception as e:  # noqa: BLE001
            st.error(f"상세정보 조회 실패: {db.explain_error(e)}\n\n{e}")
            return
        if not info:
            st.warning(f"'{pname}' 선수를 찾을 수 없습니다.")
            return
        h1, h2 = st.columns([4, 1], vertical_alignment="bottom")
        h1.subheader(f"👤 {pname}")
        with h2.popover("🗑 선수 삭제", width="stretch"):
            st.warning(f"**{pname}** 선수를 player_info 에서 삭제합니다. 되돌릴 수 없습니다. "
                       "(출주표·상담결과·경주결과의 기록은 그대로 남습니다)")
            if st.button("삭제 확인", type="primary", key=f"pdel_{pname}"):
                try:
                    A.delete(pname)
                    st.session_state[f"{STATE}_msg"] = ("ok", f"🗑 '{pname}' 선수를 삭제했습니다.")
                    s.update(mode=None, selected=None, opts=A.options())
                    if s.get("results") is not None:
                        s["results"] = s["results"][s["results"]["선수명"] != pname]
                    _bump()
                except Exception as e:  # noqa: BLE001
                    st.session_state[f"{STATE}_msg"] = ("err", f"삭제 실패 (DB는 바뀌지 않았습니다): {e}")
                st.rerun()
        ok, vals = _form(info, retire_col, False, f"{pname}_{s['ver']}")
        if ok:
            try:
                errors = A.save(pname, vals, retire_col)
            except Exception as e:  # noqa: BLE001
                st.error(f"저장 실패 (DB는 바뀌지 않았습니다): {db.explain_error(e)}\n\n{e}")
                return
            if errors:
                st.error("저장하지 않았습니다.\n\n" + "\n".join(f"- {x}" for x in errors))
                return
            s["opts"] = A.options()
            st.session_state[f"{STATE}_msg"] = ("ok", f"✅ '{pname}' 선수정보를 저장했습니다.")
            _bump()
            st.rerun()
