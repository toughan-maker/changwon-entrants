"""
출전선수상담결과 → ^ 구분 txt (창원·광명·부산 공용 화면)
출력: 회차코드^경주일(YYYY-MM-DD)^성명^기수^체중^200미터^333미터^500미터^도로^트랙^훈련일수^훈련지^훈련동참자^전회출전^훈련내용^참고사항^
      (회차코드 예: c202641 / j202643 / b202638, 줄 끝에 ^ 하나 더)
"""
from datetime import date

import pandas as pd
import requests
import streamlit as st

from common.formats import COUNSEL_COLUMNS as COLUMNS, counsel_code
from common.lepopark import to_txt_bytes
from common.sites import SITES
from common.tracks import TRACKS

SEP = "^"


def render(track: str):
    t = TRACKS[track]
    site = SITES[track]
    state_key = f"counsel_result_{t.slug}"
    use_seq = track == "창원"   # 창원 사이트만 시퀀스넘버로 회차를 고름

    st.title(f"🚴 {track}경륜 출전선수상담결과")
    if use_seq:
        st.caption("시퀀스넘버만 넣어도 되고, 년도+회차만 넣어도 됩니다. 비워 둔 값은 사이트에서 자동으로 채웁니다.")
    else:
        st.caption(f"{t.site_name} 기준 년도와 회차를 넣어 주세요. 경주일자를 비우면 해당 회차 1일차 날짜를 자동으로 넣습니다.")

    with st.form(f"counsel_query_{t.slug}"):
        cols = st.columns(4 if use_seq else 3)
        seq_in = cols[0].text_input("시퀀스넘버 (seqtimes)", placeholder="예: 25566") if use_seq else ""
        k = 1 if use_seq else 0
        date_in = cols[k].date_input("경주일자", value=None, format="YYYY-MM-DD",
                                     help="비우면 해당 회차 1일차 날짜를 자동 입력")
        year_in = cols[k + 1].text_input("년도", value="" if use_seq else str(date.today().year),
                                         placeholder=f"예: {date.today().year}")
        times_in = cols[k + 2].text_input("회차", placeholder="예: 41")

        o1, o2, _ = st.columns([1, 1, 2])
        with_header = o1.checkbox("txt 첫 줄에 항목명 포함", value=False)
        encoding = o2.selectbox("txt 인코딩", ["utf-8", "cp949"],
                                help="엑셀/메모장(구버전)에서 한글이 깨지면 cp949")
        submitted = st.form_submit_button("조회", type="primary", width="stretch")

    if submitted:
        seq_in, year_in, times_in = seq_in.strip(), year_in.strip(), times_in.strip()
        if seq_in and not seq_in.isdigit():
            st.error("시퀀스넘버는 숫자여야 합니다.")
            st.stop()
        if not use_seq and not (year_in.isdigit() and times_in.isdigit()):
            st.error("년도와 회차를 숫자로 입력해 주세요.")
            st.stop()
        try:
            with st.spinner("상담결과 페이지 수집 중..."):
                if use_seq:
                    res = site.load_counsel(year_in, times_in, seq_in, date_in)
                else:
                    res = site.load_counsel(year_in, times_in, date_in)
        except ValueError as e:
            st.error(str(e))
            st.stop()
        except requests.RequestException as e:
            st.error(f"사이트 접속 실패: {e}")
            st.stop()

        if not res["players"]:
            st.session_state.pop(state_key, None)
            st.warning("상담결과 데이터가 없습니다. 년도·회차를 확인하세요.")
            st.markdown(f"[원본 페이지 열기]({res['url']})")
            st.stop()
        if not (res["year"].isdigit() and res["times"].isdigit()):
            st.error("년도/회차를 확인할 수 없습니다. 직접 입력해 주세요.")
            st.stop()

        code = counsel_code(track, res["year"], res["times"])
        st.session_state[state_key] = {
            "code": code, "seq": res["seq"], "rdate": res["rdate"], "url": res["url"],
            "notes": res["notes"],
            "df": pd.DataFrame([[code, res["rdate"]] + p for p in res["players"]], columns=COLUMNS),
            "with_header": with_header, "encoding": encoding,
        }

    # 결과 표시 (다운로드 버튼을 눌러도 화면 유지)
    res = st.session_state.get(state_key)
    if not res:
        return
    for note in res["notes"]:
        st.info(f"참고: {note}")
    if not res["rdate"]:
        st.warning("경주일을 자동으로 찾지 못했습니다. 경주일자를 직접 입력해 주세요.")

    df = res["df"]
    m = st.columns(4 if use_seq else 3)
    m[0].metric("회차", res["code"])
    if use_seq:
        m[1].metric("시퀀스넘버", res["seq"])
    m[-2].metric("경주일", res["rdate"] or "-")
    m[-1].metric("선수 수", f"{len(df)}명")

    st.download_button(
        "📥 txt 파일 다운로드",
        data=to_txt_bytes(df, sep=SEP, header=res["with_header"], encoding=res["encoding"],
                          trailing_sep=True),
        file_name=f"counsel_{res['code']}.txt",
        mime="text/plain", type="primary", width="stretch",
        on_click="ignore",  # 다운로드해도 화면을 다시 그리지 않음
    )

    tab_table, tab_txt = st.tabs(["결과 표", "txt 미리보기"])
    with tab_table:
        st.dataframe(df, hide_index=True, width="stretch",
                     column_config={"훈련내용": st.column_config.TextColumn(width="large")})
    with tab_txt:
        # 내려받는 파일 내용 전체 (인코딩만 화면용 utf-8)
        preview = to_txt_bytes(df, sep=SEP, header=res["with_header"], trailing_sep=True).decode("utf-8")
        st.caption(f"총 {preview.count(chr(10))}줄")
        st.code(preview, language=None, height=600)

    st.markdown(f"<small>원본: <a href='{res['url']}' target='_blank'>{res['url']}</a></small>",
                unsafe_allow_html=True)
