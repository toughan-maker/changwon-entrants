"""
창원경륜 도구 모음 (Streamlit 멀티페이지 앱)

로컬 실행:
    pip install -r requirements.txt
    streamlit run app.py

새 프로그램 추가 방법:
    1) apps/ 폴더에 파일 추가 (예: apps/result.py)
       - 공통 기능은 common/lepopark.py 에서 import
       - st.set_page_config 는 여기서 한 번만 호출하므로 각 파일에서는 쓰지 않습니다.
    2) 아래 PAGES 에 st.Page 한 줄 추가
"""
import streamlit as st

st.set_page_config(page_title="창원경륜 도구", page_icon="🚴", layout="wide")

PAGES = [
    st.Page("apps/entrant.py", title="출주표", icon="📋", url_path="entrant", default=True),
    st.Page("apps/counsel.py", title="출전선수상담결과", icon="🗣️", url_path="counsel"),
    st.Page("apps/result.py", title="경주결과", icon="🏁", url_path="result"),
]

st.navigation(PAGES).run()
