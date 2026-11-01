"""
창원경륜 출주표 → CSV (Streamlit 웹앱)

로컬 실행:
    pip install -r requirements.txt
    streamlit run app.py
"""
import re
from datetime import date

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

# ───────────────────────── 설정 ─────────────────────────
BASE_UNFIX = "https://www.lepopark.or.kr/race/entrant-unfix/{date}"
BASE_FIX = "https://www.lepopark.or.kr/race/entrant/{date}"
TRACK = "창원"
TRACK_PREFIX = {"창원": "c", "부산": "b", "광명": "g"}

COLUMNS = [
    "경주번호", "경주일", "경주시간", "선수번호", "선수명", "기수", "나이",
    "기어배수", "등급", "승률", "연대율", "200미터기록", "훈련지",
    "창원점수", "종합점수", "창원", "상금순위",
]

# 예: "창원 01 경주 [우수] 출발 12:55"
RACE_TITLE_RE = re.compile(
    r"(창원|부산|광명)\s*(\d+)\s*경주\s*\[([^\]]*)\]\s*출발\s*(\d{1,2}:\d{2})"
)
KISU_AGE_RE = re.compile(r"(\d+)\s*기\s*(\d+)\s*세")
# 예: "2026년 40회 3일차" (41A회처럼 영문이 붙는 경우 포함)
ROUND_RE = re.compile(r"(\d{4})\s*년\s*(\d+)([A-Za-z]?)\s*회\s*(\d+)\s*일차")


# ───────────────────────── 파싱 함수 ─────────────────────────
def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def main_value(cell) -> str:
    """셀의 첫 줄 값만 반환. 예: '14\\n(0)' -> '14'"""
    lines = [s.strip() for s in cell.get_text("\n").split("\n") if s.strip()]
    return lines[0] if lines else ""


def normalize_record(text: str) -> str:
    """200m 기록 11”29 / 11″29 / 11.29 -> 11"29 (일반 큰따옴표로 통일)"""
    return re.sub(r"[”″.]", '"', text).strip()


def find_entry_table(heading):
    """경주 제목 다음의 첫 '기어배수' 표 (다음 경주 제목 전까지)"""
    for el in heading.find_all_next(["h3", "table"]):
        if el.name == "h3" and el is not heading and RACE_TITLE_RE.search(el.get_text(" ", strip=True)):
            return None
        if el.name == "table" and "기어" in el.get_text():
            return el
    return None


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
        return pd.DataFrame(columns=COLUMNS), None
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

            rows.append({
                "경주번호": race_id,
                "경주일": race_date,
                "경주시간": race_time,
                "선수번호": num_m.group(1) if num_m else "",
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
            })

    label = f"{year}년 {round_no.lstrip('0') or '0'}회 {int(day_no)}일차"
    return pd.DataFrame(rows, columns=COLUMNS), label


@st.cache_data(ttl=600, show_spinner=False)  # 같은 페이지는 10분간 다시 요청하지 않음
def fetch_cached(url: str) -> str:
    return fetch_html(url)


def load(date_str: str, fixed: bool):
    # 캐시에는 원본 HTML만 저장하고, 변환(파싱)은 매번 새로 실행합니다.
    # (변환 결과까지 캐시하면 코드를 고친 뒤에도 예전 형식의 결과가 10분간 나올 수 있음)
    url = (BASE_FIX if fixed else BASE_UNFIX).format(date=date_str)
    html = fetch_cached(url)
    df, label = parse(html, date_str)
    return df, label, url


# ───────────────────────── 화면 ─────────────────────────
st.set_page_config(page_title="창원경륜 출주표 CSV", page_icon="🚴", layout="wide")
st.title("🚴 창원경륜 출주표 → CSV")
st.caption("창원레포츠파크 출주표에서 창원 경주 정보를 추출해 CSV로 내려받습니다.")

with st.form("query"):
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

    # 결과 파일: 쉼표 구분 텍스트(.txt), 첫 줄(열 제목) 없이 데이터만 저장
    # BOM을 넣으면 첫 데이터 앞에 보이지 않는 문자가 붙으므로 BOM 없는 UTF-8 사용
    out_df = df.copy()
    # 기어배수: 화살표(↑↓▲▼ 등)를 없애고 숫자만 저장 (화면 표에는 원래 값 그대로 표시)
    out_df["기어배수"] = out_df["기어배수"].astype(str).str.extract(r"(\d+(?:\.\d+)?)", expand=False).fillna("")
    # 200미터기록의 큰따옴표(12"23) 때문에 CSV 모듈이 값을 "12""23"으로 감싸지 않도록
    # 따옴표 처리 없이 쉼표로만 이어서 저장 (값 안의 쉼표는 제거)
    lines = [
        ",".join(str(v).replace(",", "") for v in row)
        for row in out_df.itertuples(index=False)
    ]
    txt_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    st.download_button(
        "📥 결과 파일(.txt) 다운로드",
        data=txt_bytes,
        file_name=f"changwon_{'fix' if fixed else 'unfix'}_{date_str}.txt",
        mime="text/plain",
        type="primary",
    )

    tab_race, tab_all = st.tabs(["경주별 보기", "전체 표"])
    with tab_race:
        for (no, grade, t), g in df.groupby(["경주번호", "등급", "경주시간"], sort=False):
            st.subheader(f"{no} · [{grade}] · 출발 {t}")
            st.dataframe(
                g.drop(columns=["경주번호", "경주일", "경주시간", "등급"]),
                hide_index=True, width="stretch",
            )
    with tab_all:
        st.dataframe(df, hide_index=True, width="stretch")

    st.markdown(f"<small>원본: <a href='{url}' target='_blank'>{url}</a></small>", unsafe_allow_html=True)
