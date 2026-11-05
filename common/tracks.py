"""
경기장 설정 (Streamlit 없이 동작)

- 이름: 화면·파일에 쓰는 경기장 이름 ('창원' / '광명' / '부산')
- prefix: raceno·회차 코드 앞 글자 (c / j / b)
- slug: 메뉴 주소·다운로드 파일 이름에 쓰는 영문 이름
- site: 정보를 가져오는 사이트
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Track:
    name: str
    prefix: str
    slug: str
    site: str
    site_name: str


TRACKS = {
    "창원": Track("창원", "c", "changwon", "https://www.lepopark.or.kr", "창원레포츠파크"),
    "광명": Track("광명", "j", "gwangmyeong", "https://kcycle.or.kr", "KCYCLE(광명)"),
    "부산": Track("부산", "b", "busan", "https://www.spo1.or.kr", "스포원(부산)"),
}

TRACK_PREFIX = {name: t.prefix for name, t in TRACKS.items()}
