"""
창원레포츠파크(lepopark.or.kr) 공통 모듈 + 세 사이트 공용 요청 함수(fetch_html)
- 페이지/API 요청 (10분 캐시)
- 년도·회차·시퀀스넘버·경주일 조회
- 셀 텍스트 정리, txt 파일 변환

새 프로그램을 추가할 때는 여기 함수를 가져다 쓰면 됩니다.
    from common.lepopark import fetch_html, find_seqtimes, to_txt_bytes
"""
import re

import pandas as pd
import requests
import streamlit as st

from common import tls_fix

# ───────────────────────── 주소 ─────────────────────────
BASE = "https://www.lepopark.or.kr"

ENTRANT_FIX_URL = BASE + "/race/entrant/{date}"           # 확정출주표
ENTRANT_UNFIX_URL = BASE + "/race/entrant-unfix/{date}"   # 미확정출주표
COUNSEL_URL = BASE + "/racer/counsel"                     # 출전선수상담결과 (?seqtimes=)
RESULT_URL = BASE + "/race/result/{date}"                 # 경주결과
FINALRATE_URL = BASE + "/race/finalrate/{date}?seqrace={seq}"  # 경주별 최종배당률

RCTIMES_COUNSEL_API = BASE + "/api/race/{year}/rctimes_counsel"   # 년도별 회차·seqtimes
RCDATE_API = BASE + "/api/race/{year}/rcdate"                     # 년도별 경주일

from common.tracks import TRACK_PREFIX  # noqa: E402,F401  (예전 import 경로 유지)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": BASE + "/",
}


# ───────────────────────── 요청 ─────────────────────────
def _get(url: str, params: dict | None = None) -> requests.Response:
    # Referer 는 요청하는 사이트 주소로 (창원·광명·부산 사이트 공용)
    origin = re.match(r"https?://[^/]+", url)
    headers = {**HEADERS, "Referer": (origin.group(0) if origin else BASE) + "/"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30,
                            verify=tls_fix.bundle_for(url) if _needs_bundle(url) else True)
    except requests.exceptions.SSLError as e:
        # 서버가 중간 인증서를 빠뜨린 경우(예: 스포원) → 받아와서 다시 정상 검증
        bundle = tls_fix.bundle_for(url) if tls_fix.is_cert_error(e) else None
        if not bundle:
            raise
        _BUNDLE_HOSTS.add(_host(url))
        resp = requests.get(url, params=params, headers=headers, timeout=30, verify=bundle)
    resp.raise_for_status()
    return resp


_BUNDLE_HOSTS: set[str] = set()   # 중간 인증서 보완이 필요했던 사이트 (다음부터 바로 사용)


def _host(url: str) -> str:
    m = re.match(r"https?://([^/:]+)", url)
    return m.group(1) if m else ""


def _needs_bundle(url: str) -> bool:
    return _host(url) in _BUNDLE_HOSTS


@st.cache_data(ttl=600, show_spinner=False)  # 같은 페이지는 10분간 다시 요청하지 않음
def fetch_html(url: str) -> str:
    """페이지 HTML. 캐시에는 원본 HTML만 저장하고 파싱은 매번 새로 실행합니다.
    (파싱 결과까지 캐시하면 코드를 고친 뒤에도 예전 결과가 10분간 나올 수 있음)"""
    resp = _get(url)
    if "charset" not in resp.headers.get("Content-Type", "").lower():
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


@st.cache_data(ttl=600, show_spinner=False)
def fetch_json(url: str):
    return _get(url).json()


# ───────────────────────── 회차·경주일 조회 ─────────────────────────
def rctimes_list(year: str) -> list[dict]:
    """[{seqtimes, rctimes, rcyear, ...}, ...] (상담결과 기준 회차 목록)"""
    return fetch_json(RCTIMES_COUNSEL_API.format(year=year))


def rcdate_list(year: str) -> list[dict]:
    """[{rcdate:'20261030', rctimes:'41', rcdays:'1', seqtimes:25566, ...}, ...]"""
    return fetch_json(RCDATE_API.format(year=year))


def find_seqtimes(year: str, times) -> str | None:
    """년도 + 회차 → 시퀀스넘버(seqtimes)"""
    for d in rctimes_list(year):
        if int(d["rctimes"]) == int(times):
            return str(d["seqtimes"])
    return None


def find_race_dates(year: str, seqtimes) -> list[str]:
    """해당 회차의 경주일 목록 (YYYYMMDD, 오름차순). 실패하면 빈 리스트."""
    try:
        data = rcdate_list(year)
    except requests.RequestException:
        return []
    return sorted(d["rcdate"] for d in data
                  if str(d.get("seqtimes")) == str(seqtimes) and d.get("rcdate"))


def first_race_date(year: str, seqtimes) -> str:
    """해당 회차 1일차 경주일 (YYYYMMDD). 못 찾으면 ''."""
    dates = find_race_dates(year, seqtimes)
    return dates[0] if dates else ""


# ───────────────────────── 텍스트 정리 ─────────────────────────
def clean(text) -> str:
    """연속 공백·줄바꿈을 한 칸으로"""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text).replace("\xa0", " ")).strip()


def main_value(cell) -> str:
    """셀의 첫 줄 값만 반환. 예: '14\\n(0)' -> '14'"""
    lines = [s.strip() for s in cell.get_text("\n").split("\n") if s.strip()]
    return lines[0] if lines else ""


# ───────────────────────── 파일 변환 ─────────────────────────
def to_txt_bytes(frame: pd.DataFrame, sep: str = ",", header: bool = False,
                 encoding: str = "utf-8", trailing_sep: bool = False) -> bytes:
    """DataFrame → 구분자 txt (BOM 없음).
    - 값 안에 들어 있는 구분자 문자는 지웁니다(열이 밀리지 않도록).
    - CSV 따옴표 처리는 하지 않습니다. (200m 기록 12"23 이 "12""23" 으로 바뀌지 않도록)
    - trailing_sep=True 면 줄마다 끝에 구분자를 하나 더 붙입니다. (예: ...^참고사항^)"""
    end = sep if trailing_sep else ""
    lines = []
    if header:
        lines.append(sep.join(str(c) for c in frame.columns) + end)
    lines += [sep.join(str(v).replace(sep, "") for v in row) + end
              for row in frame.itertuples(index=False)]
    return ("\n".join(lines) + "\n").encode(encoding, errors="replace")
