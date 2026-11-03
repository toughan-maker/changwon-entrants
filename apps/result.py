"""
창원경륜 경주결과 → txt (DB 업로드용, 쉼표 구분)
- 선수별 경주결과 파일 / 경주정보(배당) 파일 2개 생성
"""
from datetime import date

import requests
import streamlit as st

from common.lepopark import RESULT_URL, fetch_html, to_txt_bytes
from common.result_parser import parse_result

TRACK = "창원"

st.title("🏁 창원경륜 경주결과 → TXT")
st.caption("창원레포츠파크 경주결과에서 창원 경주를 추출해 DB 업로드용 쉼표 구분 txt 2개로 내려받습니다.")

with st.form("result_query"):
    c1, c2, c3 = st.columns(3)
    with c1:
        race_day = st.date_input("경주일자", value=date.today(), format="YYYY-MM-DD")
    with c2:
        year = st.text_input("년도", value=str(date.today().year), max_chars=4)
    with c3:
        round_no = st.text_input("회차", value="", placeholder="예: 33")
    with st.expander("출력 옵션"):
        o1, o2, o3 = st.columns(3)
        with o1:
            style = st.radio("200m·최종주회 표기", ['11"76', "11.76"], horizontal=True)
        with o2:
            decimals = st.selectbox("소수 자리수", [2, 3, 4], index=0,
                                    help="2등 이하는 1등 기록 + 주행시간 차이로 계산합니다.")
        with o3:
            header = st.checkbox("첫 줄에 필드명 포함", value=False)
    submitted = st.form_submit_button("조회", type="primary", width="stretch")

if submitted:
    year, round_no = year.strip(), round_no.strip()
    if not (year.isdigit() and len(year) == 4):
        st.error("년도는 4자리 숫자로 입력해 주세요.")
        st.stop()
    if not round_no:
        st.error("회차를 입력해 주세요.")
        st.stop()

    date_str = race_day.strftime("%Y%m%d")
    url = RESULT_URL.format(date=date_str)
    try:
        with st.spinner("경주결과를 가져오는 중..."):
            html = fetch_html(url)
    except requests.RequestException as e:
        st.error(f"페이지를 가져오지 못했습니다: {e}")
        st.stop()

    players_df, races_df, info = parse_result(
        html, year=year, round_no=round_no, race_date=race_day.strftime("%Y-%m-%d"),
        track=TRACK, decimals=decimals, style="quote" if style.startswith('11"') else "decimal",
    )

    if races_df.empty:
        st.warning(f"{race_day:%Y-%m-%d} 경주결과에서 창원 경주를 찾지 못했습니다. "
                   "경주가 없는 날이거나 아직 결과가 올라오지 않았을 수 있습니다.")
        st.markdown(f"[원본 페이지 열기]({url})")
        st.stop()

    # 입력값과 페이지 정보 비교
    page_round = info.get("round", "")
    in_round = f"{int(round_no):02d}" if round_no.isdigit() else round_no.upper()
    if info.get("year") and (info["year"] != year or page_round != in_round):
        st.warning(f"입력값({year}년 {round_no}회)과 페이지 정보"
                   f"({info['year']}년 {page_round.lstrip('0')}회 {int(info['day'])}일차)가 다릅니다. "
                   "raceno는 입력값 기준으로 만들었습니다.")
    bad = races_df[races_df["raceno"].str.len() != 11]
    if not bad.empty:
        st.warning(f"raceno가 11자리가 아닙니다: {', '.join(bad['raceno'])}")
    if not info.get("day"):
        st.warning("페이지에서 일차를 찾지 못해 01로 넣었습니다.")

    day_label = f" {int(info['day'])}일차" if info.get("day") else ""
    st.success(f"{year}년 {round_no}회{day_label} · 창원 {len(races_df)}개 경주, 선수 {len(players_df)}명")

    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "📥 선수별 경주결과(.txt)", data=to_txt_bytes(players_df, header=header),
            file_name=f"changwon_result_player_{date_str}.txt",
            mime="text/plain", type="primary", width="stretch",
        )
    with d2:
        st.download_button(
            "📥 경주정보(.txt)", data=to_txt_bytes(races_df, header=header),
            file_name=f"changwon_result_race_{date_str}.txt",
            mime="text/plain", type="primary", width="stretch",
        )

    tab_p, tab_r = st.tabs(["선수별 경주결과", "경주정보"])
    with tab_p:
        for no, g in players_df.groupby("raceno", sort=False):
            grade = g["경주등급"].iloc[0]
            st.subheader(f"{no} · [{grade}]")
            st.dataframe(g.drop(columns=["raceno", "경기장", "경주일자", "경주등급"]),
                         hide_index=True, width="stretch")
    with tab_r:
        st.dataframe(races_df, hide_index=True, width="stretch")

    st.markdown(f"<small>원본: <a href='{url}' target='_blank'>{url}</a></small>",
                unsafe_allow_html=True)
