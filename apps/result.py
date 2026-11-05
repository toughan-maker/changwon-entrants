"""
경주결과 → txt (DB 업로드용, 쉼표 구분) — 창원·광명·부산 공용 화면
- 선수별 경주결과 파일 / 경주정보(배당) 파일 2개 생성
"""
from datetime import date

import requests
import streamlit as st

from common.lepopark import to_txt_bytes
from common.sites import SITES
from common.tracks import TRACKS


def render(track: str):
    t = TRACKS[track]
    site = SITES[track]

    st.title(f"🏁 {track}경륜 경주결과 → TXT")
    st.caption(f"{t.site_name} 경주결과에서 {track} 경주를 추출해 DB 업로드용 쉼표 구분 txt 2개로 내려받습니다.")

    with st.form(f"result_query_{t.slug}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            race_day = st.date_input("경주일자", value=date.today(), format="YYYY-MM-DD")
        with c2:
            year = st.text_input("년도", value=str(date.today().year), max_chars=4)
        with c3:
            round_no = st.text_input("회차", value="", placeholder="예: 33")
        submitted = st.form_submit_button("조회", type="primary", width="stretch")

    if not submitted:
        return

    year, round_no = year.strip(), round_no.strip()
    if not (year.isdigit() and len(year) == 4):
        st.error("년도는 4자리 숫자로 입력해 주세요.")
        st.stop()
    if not round_no:
        st.error("회차를 입력해 주세요.")
        st.stop()

    date_str = race_day.strftime("%Y%m%d")
    try:
        with st.spinner("경주결과와 최종배당률을 가져오는 중... (경주 수에 따라 시간이 걸립니다)"):
            res = site.load_result(race_day, year, round_no)
    except requests.RequestException as e:
        st.error(f"페이지를 가져오지 못했습니다: {e}")
        st.stop()

    players_df, races_df, url = res["players_df"], res["races_df"], res["url"]
    if races_df.empty:
        st.warning(f"{race_day:%Y-%m-%d} 경주결과에서 {track} 경주를 찾지 못했습니다. "
                   "경주가 없는 날이거나 아직 결과가 올라오지 않았을 수 있습니다.")
        st.markdown(f"[원본 페이지 열기]({url})")
        st.stop()

    for w in res["warnings"]:
        st.warning(w)

    # 인기순위를 계산하지 못한 경주
    no_pop = [r for r, g in players_df.groupby("raceno") if (g["인기순위"] == "").all()]
    if no_pop:
        st.warning(f"인기순위를 계산하지 못한 경주가 있어 빈칸으로 저장됩니다: {', '.join(no_pop)}")

    # 입력값과 페이지 정보 비교
    page = res.get("page") or {}
    in_round = f"{int(round_no):02d}" if round_no.isdigit() else round_no.upper()
    if page.get("year") and (page["year"] != year or page.get("round") != in_round):
        st.warning(f"입력값({year}년 {round_no}회)과 페이지 정보"
                   f"({page['year']}년 {page['round'].lstrip('0')}회 {int(page['day'])}일차)가 다릅니다. "
                   "raceno는 입력값 기준으로 만들었습니다.")
    bad = races_df[races_df["raceno"].str.len() != 11]
    if not bad.empty:
        st.warning(f"raceno가 11자리가 아닙니다: {', '.join(bad['raceno'])}")

    day_label = f" {int(page['day'])}일차" if page.get("day") else ""
    st.success(f"{year}년 {round_no}회{day_label} · {track} {len(races_df)}개 경주, 선수 {len(players_df)}명")

    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "📥 선수별 경주결과(.txt)", data=to_txt_bytes(players_df, trailing_sep=True),
            file_name=f"{t.slug}_result_player_{date_str}.txt",
            mime="text/plain", type="primary", width="stretch",
            on_click="ignore",  # 다운로드해도 화면을 다시 그리지 않음
        )
    with d2:
        st.download_button(
            "📥 경주정보(.txt)", data=to_txt_bytes(races_df, trailing_sep=True),
            file_name=f"{t.slug}_result_race_{date_str}.txt",
            mime="text/plain", type="primary", width="stretch",
            on_click="ignore",
        )

    tab_p, tab_r = st.tabs(["선수별 경주결과", "경주정보"])
    with tab_p:
        for no, g in players_df.groupby("raceno", sort=False):
            st.subheader(f"{no} · [{g['경주등급'].iloc[0]}]")
            st.dataframe(g.drop(columns=["raceno", "경기장", "경주일자", "경주등급"]),
                         hide_index=True, width="stretch")
    with tab_r:
        st.dataframe(races_df, hide_index=True, width="stretch")

    st.markdown(f"<small>원본: <a href='{url}' target='_blank'>{url}</a></small>",
                unsafe_allow_html=True)
