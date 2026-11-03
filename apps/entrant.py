"""
창원경륜 출주표 → txt
(기존 app.py 의 출주표 프로그램. 동작과 출력 형식은 그대로입니다.)
"""
import re
from datetime import date

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

from common.lepopark import (
    ENTRANT_FIX_URL, ENTRANT_UNFIX_URL, TRACK_PREFIX,
    fetch_html, main_value, to_txt_bytes,
)

# ───────────────────────── 설정 ─────────────────────────
TRACK = "창원"

COLUMNS = [
    "경주번호", "경주일", "경주시간", "선수번호", "선수명", "기수", "나이",
    "기어배수", "등급", "승률", "연대율", "200미터기록", "훈련지",
    "창원점수", "종합점수", "창원", "상금순위",
]

# 추가 파일 열: 경주번호, 이름, 기어배수, 0, 0, 0, 잔여점수
EXTRA_COLUMNS = ["경주번호", "선수명", "기어배수", "값1", "값2", "값3", "잔여점수"]

# 예: "창원 01 경주 [우수] 출발 12:55"
RACE_TITLE_RE = re.compile(
    r"(창원|부산|광명)\s*(\d+)\s*경주\s*\[([^\]]*)\]\s*출발\s*(\d{1,2}:\d{2})"
)
KISU_AGE_RE = re.compile(r"(\d+)\s*기\s*(\d+)\s*세")
# 예: "2026년 40회 3일차" (41A회처럼 영문이 붙는 경우 포함)
ROUND_RE = re.compile(r"(\d{4})\s*년\s*(\d+)([A-Za-z]?)\s*회\s*(\d+)\s*일차")


# ───────────────────────── 파싱 함수 ─────────────────────────
def normalize_record(text: str) -> str:
    """200m 기록 11”29 / 11″29 / 11.29 -> 11"29 (일반 큰따옴표로 통일)"""
    return re.sub(r"[”″.]", '"', text).strip()


def _find_table_after(heading, keyword):
    """경주 제목 다음에서 keyword가 들어간 첫 표 (다음 경주 제목 전까지)"""
    for el in heading.find_all_next(["h3", "table"]):
        if el.name == "h3" and el is not heading and RACE_TITLE_RE.search(el.get_text(" ", strip=True)):
            return None
        if el.name == "table" and keyword in el.get_text():
            return el
    return None


def find_entry_table(heading):
    """출주표('기어배수') 표"""
    return _find_table_after(heading, "기어")


def find_penalty_table(heading):
    """규칙 위반 점수('잔여점수') 표"""
    return _find_table_after(heading, "잔여")


def parse_residual_points(table):
    """{선수번호: 잔여점수} — 각 선수 행의 마지막 칸이 잔여점수"""
    result = {}
    if table is None:
        return result
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if not tds or not tds[0].find("a", href=re.compile(r"/racer/")):
            continue
        num_m = re.match(r"\s*(\d+)", tds[0].get_text(" ", strip=True))
        if num_m:
            result[num_m.group(1)] = main_value(tds[-1])
    return result


def parse_race_date(soup, date_arg: str) -> str:
    """경주일을 YY-MM-DD 형식으로 반환. 예: 26-11-01"""
    m = re.search(r"\((\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\)", soup.get_text(" "))
    if m:
        return f"{m.group(1)[2:]}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return f"{date_arg[2:4]}-{date_arg[4:6]}-{date_arg[6:8]}"


def parse_round(soup):
    """페이지 제목에서 (년도, 회차, 일차) 추출. 예: ('2026', '40', '03')"""
    m = ROUND_RE.search(soup.get_text(" "))
    if not m:
        return None
    year = m.group(1)
    round_no = f"{int(m.group(2)):02d}{m.group(3).upper()}"
    day_no = f"{int(m.group(4)):02d}"
    return year, round_no, day_no


def parse(html: str, date_arg: str, track: str = TRACK):
    """반환: (DataFrame, 회차정보 문자열 또는 None)"""
    soup = BeautifulSoup(html, "html.parser")
    race_date = parse_race_date(soup, date_arg)
    round_info = parse_round(soup)
    if round_info is None:
        return pd.DataFrame(columns=COLUMNS + ["잔여점수"]), None
    year, round_no, day_no = round_info
    prefix = TRACK_PREFIX[track]
    rows = []

    for heading in soup.find_all(["h2", "h3", "h4"]):
        m = RACE_TITLE_RE.search(heading.get_text(" ", strip=True))
        if not m or m.group(1) != track:
            continue
        race_no, race_grade, race_time = int(m.group(2)), m.group(3).strip(), m.group(4)
        race_id = f"{prefix}{year}{round_no}{day_no}{race_no:02d}"  # 예: c2026400301

        table = find_entry_table(heading)
        if table is None:
            continue
        residual = parse_residual_points(find_penalty_table(heading))

        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds or not tds[0].find("a", href=re.compile(r"/racer/")):
                continue
            if len(tds) < 17:
                continue

            first = tds[0]
            first_text = first.get_text(" ", strip=True)
            num_m = re.match(r"\s*(\d+)", first_text)
            ka = KISU_AGE_RE.search(first_text)
            player_no = num_m.group(1) if num_m else ""

            rows.append({
                "경주번호": race_id,
                "경주일": race_date,
                "경주시간": race_time,
                "선수번호": player_no,
                "선수명": first.find("a").get_text(strip=True),
                "기수": ka.group(1) if ka else "",
                "나이": ka.group(2) if ka else "",
                "기어배수": main_value(tds[1]),
                "등급": race_grade,  # 경주 등급
                "승률": main_value(tds[4]),
                "연대율": main_value(tds[5]),
                "200미터기록": normalize_record(main_value(tds[2])),
                "훈련지": main_value(tds[3]),
                "창원점수": main_value(tds[14]),
                "종합점수": main_value(tds[15]),
                "창원": track,  # 경주장 이름 (고정값 '창원')
                "상금순위": main_value(tds[16]).split("/")[0].strip(),
                "잔여점수": residual.get(player_no, ""),  # 추가 파일용
            })

    label = f"{year}년 {round_no.lstrip('0') or '0'}회 {int(day_no)}일차"
    return pd.DataFrame(rows, columns=COLUMNS + ["잔여점수"]), label


def load(date_str: str, fixed: bool):
    url = (ENTRANT_FIX_URL if fixed else ENTRANT_UNFIX_URL).format(date=date_str)
    df, label = parse(fetch_html(url), date_str)
    return df, label, url


# ───────────────────────── 화면 ─────────────────────────
st.title("🚴 창원경륜 출주표 → CSV")
st.caption("창원레포츠파크 출주표에서 창원 경주 정보를 추출해 CSV로 내려받습니다.")

with st.form("entrant_query"):
    col1, col2 = st.columns(2)
    with col1:
        kind = st.radio("출주표 구분", ["확정", "미확정"], index=1, horizontal=True)
    with col2:
        race_day = st.date_input("경주일", value=date.today(), format="YYYY-MM-DD")
    submitted = st.form_submit_button("조회", type="primary", width="stretch")

if submitted:
    date_str = race_day.strftime("%Y%m%d")
    fixed = kind == "확정"
    try:
        with st.spinner("출주표를 가져오는 중..."):
            df, label, url = load(date_str, fixed)
    except requests.RequestException as e:
        st.error(f"페이지를 가져오지 못했습니다: {e}")
        st.stop()

    if df.empty:
        st.warning(
            f"{race_day:%Y-%m-%d} {kind}출주표에서 창원 경주를 찾지 못했습니다. "
            "경주가 없는 날이거나 아직 출주표가 올라오지 않았을 수 있습니다."
        )
        st.markdown(f"[원본 페이지 열기]({url})")
        st.stop()

    st.success(f"{label} · {kind}출주표 · 창원 {df['경주번호'].nunique()}개 경주, 선수 {len(df)}명")

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

    base_name = f"changwon_{'fix' if fixed else 'unfix'}_{date_str}"
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "📥 결과 파일(.txt) 다운로드",
            data=to_txt_bytes(main_df),
            file_name=f"{base_name}.txt",
            mime="text/plain", type="primary", width="stretch",
            on_click="ignore",  # 다운로드해도 화면을 다시 그리지 않음
        )
    with c2:
        st.download_button(
            "📥 추가 파일(.txt) 다운로드",
            data=to_txt_bytes(extra_df),
            file_name=f"{base_name}_extra.txt",
            mime="text/plain", type="primary", width="stretch",
            on_click="ignore",  # 다운로드해도 화면을 다시 그리지 않음
        )

    view_df = df[COLUMNS]
    tab_race, tab_all, tab_extra = st.tabs(["경주별 보기", "전체 표", "추가 파일 미리보기"])
    with tab_race:
        for (no, grade, t), g in view_df.groupby(["경주번호", "등급", "경주시간"], sort=False):
            st.subheader(f"{no} · [{grade}] · 출발 {t}")
            st.dataframe(
                g.drop(columns=["경주번호", "경주일", "경주시간", "등급"]),
                hide_index=True, width="stretch",
            )
    with tab_all:
        st.dataframe(view_df, hide_index=True, width="stretch")
    with tab_extra:
        st.caption("경주번호, 이름, 기어배수, 0, 0, 0, 잔여점수 순서로 저장됩니다.")
        st.dataframe(extra_df, hide_index=True, width="stretch")

    st.markdown(f"<small>원본: <a href='{url}' target='_blank'>{url}</a></small>", unsafe_allow_html=True)
