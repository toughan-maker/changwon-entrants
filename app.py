"""
경륜 도구 모음 (Streamlit 멀티페이지 앱) — 창원 / 광명 / 부산

로컬 실행:
    pip install -r requirements.txt
    streamlit run app.py

구조:
    apps/entrant.py, counsel.py, result.py   화면 (render(경기장) 하나로 세 경기장 공용)
    common/site_lepopark.py                  창원 사이트에서 가져오기
    common/site_kcycle.py                    광명 사이트에서 가져오기
    common/site_spo1.py                      부산 사이트에서 가져오기
    common/formats.py, result_parser.py      출력 형식 (세 경기장 공통)
    common/tracks.py                         경기장 설정 (raceno 접두어 c / j / b 등)

새 프로그램 추가 방법:
    1) apps/ 폴더에 render(track) 함수를 가진 파일 추가
    2) 아래 MENUS 에 한 줄 추가 → 세 경기장 메뉴에 모두 생깁니다.
"""
import streamlit as st

from apps import admin_db, admin_login, counsel, entrant, manage_chulju, manage_counsel, manage_kyocha, manage_week, result
from common import auth
from common.tracks import TRACKS

st.set_page_config(page_title="경륜 도구", page_icon="🚴", layout="wide")

# (화면 모듈, 메뉴 이름, 아이콘, 주소 이름)
MENUS = [
    (entrant, "출주표", "📋", "entrant"),
    (counsel, "출전선수상담결과", "🗣️", "counsel"),
    (result, "경주결과", "🏁", "result"),
]


def _page(module, track):
    def page():
        module.render(track)
    page.__name__ = f"{module.__name__.split('.')[-1]}_{TRACKS[track].slug}"
    return page


pages = {}
for track, t in TRACKS.items():
    pages[track] = [
        st.Page(
            _page(module, track), title=title, icon=icon,
            # 창원은 예전 주소(/entrant 등) 그대로, 광명·부산은 /entrant-gwangmyeong 형식
            url_path=path if track == "창원" else f"{path}-{t.slug}",
            default=(track == next(iter(TRACKS)) and path == "entrant"),  # 맨 위 경기장의 출주표
        )
        for module, title, icon, path in MENUS
    ]

# 관리 메뉴 (관리자 비밀번호 필요)
# 관리 메뉴: 로그인은 모두, 출주표 관리는 관리자 이상, DB 연결 테스트는 슈퍼관리자에게만 보임
pages["관리"] = [st.Page(admin_login.render, title="관리자 로그인", icon="🔑", url_path="admin-login")]
if auth.is_admin():   # 관리자·슈퍼관리자
    pages["관리"].append(st.Page(manage_chulju.render, title="출주표 관리", icon="📝", url_path="manage-chulju"))
    pages["관리"].append(st.Page(manage_counsel.render, title="상담결과 관리", icon="🗣️", url_path="manage-counsel"))
    pages["관리"].append(st.Page(manage_kyocha.render, title="교차경주 관리", icon="🔀", url_path="manage-kyocha"))
    pages["관리"].append(st.Page(manage_week.render, title="짝수 달력 변경", icon="📅", url_path="manage-week"))
if auth.is_super():
    pages["관리"].append(st.Page(admin_db.render, title="DB 연결 테스트", icon="🔌", url_path="admin-db"))

auth.sidebar_status()

st.navigation(pages).run()
