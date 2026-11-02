"""
창원경륜 출전선수상담결과 → ^ 구분 txt
출력: c년도회차^경주일(YYYY-MM-DD)^성명^기수^체중^200미터^333미터^500미터^도로^트랙^훈련일수^훈련지^훈련동참자^훈련내용^참고사항^  (줄 끝에 ^ 하나 더)
"""
import re
from datetime import date

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

from common.lepopark import (
    COUNSEL_URL, clean, fetch_html, find_seqtimes, first_race_date, to_txt_bytes,
)

TRACK_CODE = "c"   # 창원
SEP = "^"

COLUMNS = ["회차", "경주일", "성명", "기수", "체중", "200미터", "333미터", "500미터",
           "도로", "트랙", "훈련일수", "훈련지", "훈련동참자", "훈련내용", "참고사항"]


# ───────────────────────── 파싱 ─────────────────────────
def parse_counsel(html: str):
    """페이지 → (년도, 회차, seqtimes, 선수행 리스트)"""
    soup = BeautifulSoup(html, "html.parser")
    y = soup.select_one("#rcyear option[selected]")
    t = soup.select_one("#rctimes option[selected]")
    year = y.get("value", "").strip() if y else ""
    times = re.sub(r"\D", "", t.get_text()) if t else ""
    seq = t.get("value", "").strip() if t else ""

    players = []
    for table in soup.select("table.training-table"):
        for tr in table.select("tbody tr"):
            tds = [clean(td.get_text(" ")) for td in tr.find_all("td")]
            if len(tds) < 14:
                continue
            name = re.sub(r"\s*\(.*?\)\s*", "", tds[0]).strip()   # '심상훈 (후보)' → '심상훈'
            # 0성명 1기수 2체중 3:200 4:333 5:500 6도로 7트랙 8훈련일수
            # 9훈련지 10훈련동참자 11전회출전(제외) 12훈련내용 13참고사항
            players.append([name, tds[1], tds[2], tds[3], tds[4], tds[5],
                            tds[6], tds[7], tds[8], tds[9], tds[10], tds[12], tds[13]])
    return year, times, seq, players


def counsel_url(seqtimes: str | None) -> str:
    return f"{COUNSEL_URL}?seqtimes={seqtimes}" if seqtimes else COUNSEL_URL


# ───────────────────────── 화면 ─────────────────────────
st.title("🚴 창원경륜 출전선수상담결과")
st.caption("시퀀스넘버만 넣어도 되고, 년도+회차만 넣어도 됩니다. 비워 둔 값은 사이트에서 자동으로 채웁니다.")

with st.form("counsel_query"):
    c1, c2, c3, c4 = st.columns(4)
    seq_in = c1.text_input("시퀀스넘버 (seqtimes)", placeholder="예: 25566")
    date_in = c2.date_input("경주일자", value=None, format="YYYY-MM-DD",
                            help="비우면 해당 회차 1일차 날짜를 자동 입력")
    year_in = c3.text_input("년도", placeholder=f"예: {date.today().year}")
    times_in = c4.text_input("회차", placeholder="예: 41")

    o1, o2, _ = st.columns([1, 1, 2])
    with_header = o1.checkbox("txt 첫 줄에 항목명 포함", value=False)
    encoding = o2.selectbox("txt 인코딩", ["utf-8", "cp949"],
                            help="엑셀/메모장(구버전)에서 한글이 깨지면 cp949")
    submitted = st.form_submit_button("조회", type="primary", width="stretch")

if submitted:
    seq_in, year_in, times_in = seq_in.strip(), year_in.strip(), times_in.strip()
    try:
        # 1) 시퀀스넘버 결정 (없으면 년도+회차로 찾기)
        seq = seq_in
        if seq and not seq.isdigit():
            st.error("시퀀스넘버는 숫자여야 합니다.")
            st.stop()
        if not seq and year_in and times_in:
            with st.spinner("회차 번호 조회 중..."):
                seq = find_seqtimes(year_in, times_in)
            if not seq:
                st.error(f"{year_in}년 {times_in}회차를 찾을 수 없습니다.")
                st.stop()

        # 2) 페이지 수집 (seq 없으면 최신 회차)
        with st.spinner("상담결과 페이지 수집 중..."):
            p_year, p_times, p_seq, players = parse_counsel(fetch_html(counsel_url(seq)))
        seq = seq or p_seq

        if not players:
            st.warning("상담결과 데이터가 없습니다. 시퀀스넘버를 확인하세요.")
            st.markdown(f"[원본 페이지 열기]({counsel_url(seq)})")
            st.stop()

        # 3) 년도/회차/경주일: 입력값 우선, 없으면 자동
        year = year_in or p_year
        times = times_in or p_times
        if not (year.isdigit() and times.isdigit()):
            st.error("년도/회차를 확인할 수 없습니다. 직접 입력해 주세요.")
            st.stop()
        if p_year and p_times and (year != p_year or int(times) != int(p_times)):
            st.info(f"참고: 페이지 기준은 {p_year}년 {p_times}회차입니다. "
                    f"입력값({year}년 {times}회차)으로 표기합니다.")

        # 경주일 형식: YYYY-MM-DD (예: 2026-10-29)
        if date_in:
            rdate = date_in.strftime("%Y-%m-%d")
        else:
            d = first_race_date(year, seq)          # API 값은 YYYYMMDD
            rdate = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""
            if not rdate:
                st.warning("경주일을 자동으로 찾지 못했습니다. 경주일자를 직접 입력해 주세요.")

        code = f"{TRACK_CODE}{year}{int(times):02d}"
        st.session_state["counsel_result"] = {
            "code": code, "seq": seq, "rdate": rdate,
            "df": pd.DataFrame([[code, rdate] + p for p in players], columns=COLUMNS),
            "with_header": with_header, "encoding": encoding,
        }
    except requests.RequestException as e:
        st.error(f"사이트 접속 실패: {e}")
        st.stop()

# 결과 표시 (다운로드 버튼을 눌러도 화면 유지)
res = st.session_state.get("counsel_result")
if res:
    df = res["df"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("회차", res["code"])
    m2.metric("시퀀스넘버", res["seq"])
    m3.metric("경주일", res["rdate"] or "-")
    m4.metric("선수 수", f"{len(df)}명")

    st.download_button(
        "📥 txt 파일 다운로드",
        data=to_txt_bytes(df, sep=SEP, header=res["with_header"], encoding=res["encoding"],
                          trailing_sep=True),
        file_name=f"counsel_{res['code']}.txt",
        mime="text/plain", type="primary", width="stretch",
    )

    tab_table, tab_txt = st.tabs(["결과 표", "txt 미리보기"])
    with tab_table:
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"훈련내용": st.column_config.TextColumn(width="large")})
    with tab_txt:
        preview = to_txt_bytes(df.head(10), sep=SEP, header=res["with_header"], trailing_sep=True).decode("utf-8")
        st.code(preview, language=None)

    url = counsel_url(res["seq"])
    st.markdown(f"<small>원본: <a href='{url}' target='_blank'>{url}</a></small>", unsafe_allow_html=True)
