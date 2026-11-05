"""
출주표 → txt (창원·광명·부산 공용 화면)
결과 파일: 경주번호, 경주일, 경주시간, 선수번호, 선수명, 기수, 나이, 기어배수, 등급, 승률, 연대율,
          200미터기록, 훈련지, 경기장점수, 종합점수, 경기장, 상금순위
추가 파일: 경주번호(회차·일차까지), 이름, 기어배수, 0, 0, 0, 잔여점수
"""
from datetime import date

import pandas as pd
import requests
import streamlit as st

from common.formats import ENTRANT_COLUMNS as COLUMNS, EXTRA_COLUMNS
from common.lepopark import to_txt_bytes
from common.sites import SITES
from common.tracks import TRACKS


def render(track: str):
    t = TRACKS[track]
    site = SITES[track]

    st.title(f"🚴 {track}경륜 출주표 → TXT")
    st.caption(f"{t.site_name} 출주표에서 {track} 경주 정보를 추출해 txt로 내려받습니다.")

    with st.form(f"entrant_query_{t.slug}"):
        col1, col2 = st.columns(2)
        with col1:
            kind = st.radio("출주표 구분", ["확정", "미확정"], index=1, horizontal=True)
        with col2:
            race_day = st.date_input("경주일", value=date.today(), format="YYYY-MM-DD")
        submitted = st.form_submit_button("조회", type="primary", width="stretch")

    if not submitted:
        return

    date_str = race_day.strftime("%Y%m%d")
    fixed = kind == "확정"
    try:
        with st.spinner("출주표를 가져오는 중..."):
            df, label, url = site.load_entrant(race_day, fixed)
    except requests.RequestException as e:
        st.error(f"페이지를 가져오지 못했습니다: {e}")
        st.stop()

    if df.empty:
        st.warning(
            f"{race_day:%Y-%m-%d} {kind}출주표에서 {track} 경주를 찾지 못했습니다. "
            "경주가 없는 날이거나 아직 출주표가 올라오지 않았을 수 있습니다."
        )
        st.markdown(f"[원본 페이지 열기]({url})")
        st.stop()

    st.success(f"{label} · {kind}출주표 · {track} {df['경주번호'].nunique()}개 경주, 선수 {len(df)}명")

    gear_clean = df["기어배수"].astype(str).str.extract(r"(\d+(?:\.\d+)?)", expand=False).fillna("")

    # 메인 결과 파일 (기어배수 화살표 제거)
    main_df = df[COLUMNS].copy()
    main_df["기어배수"] = gear_clean

    # 추가 파일: 경주번호, 이름, 기어배수, 0, 0, 0, 잔여점수
    extra_df = pd.DataFrame({
        # 끝의 경주번호 2자리를 뺀 회차·일차까지만 표시 (c2026400301 -> c20264003)
        "경주번호": df["경주번호"].str[:-2],
        "선수명": df["선수명"],
        "기어배수": gear_clean,
        "값1": 0, "값2": 0, "값3": 0,
        "잔여점수": df["잔여점수"],
    })[EXTRA_COLUMNS]

    if (df["잔여점수"] == "").any():
        st.warning("일부 선수의 잔여점수를 찾지 못해 빈칸으로 저장됩니다.")

    base_name = f"{t.slug}_{'fix' if fixed else 'unfix'}_{date_str}"
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "📥 결과 파일(.txt) 다운로드", data=to_txt_bytes(main_df),
            file_name=f"{base_name}.txt", mime="text/plain", type="primary", width="stretch",
            on_click="ignore",  # 다운로드해도 화면을 다시 그리지 않음
        )
    with c2:
        st.download_button(
            "📥 추가 파일(.txt) 다운로드", data=to_txt_bytes(extra_df),
            file_name=f"{base_name}_extra.txt", mime="text/plain", type="primary", width="stretch",
            on_click="ignore",
        )

    view_df = df[COLUMNS].rename(columns={"경기장점수": f"{track}점수"})
    tab_race, tab_all, tab_extra = st.tabs(["경주별 보기", "전체 표", "추가 파일 미리보기"])
    with tab_race:
        for (no, grade, tm), g in view_df.groupby(["경주번호", "등급", "경주시간"], sort=False):
            st.subheader(f"{no} · [{grade}] · 출발 {tm}")
            st.dataframe(g.drop(columns=["경주번호", "경주일", "경주시간", "등급"]),
                         hide_index=True, width="stretch")
    with tab_all:
        st.dataframe(view_df, hide_index=True, width="stretch")
    with tab_extra:
        st.caption("경주번호, 이름, 기어배수, 0, 0, 0, 잔여점수 순서로 저장됩니다.")
        st.dataframe(extra_df, hide_index=True, width="stretch")

    st.markdown(f"<small>원본: <a href='{url}' target='_blank'>{url}</a></small>", unsafe_allow_html=True)
