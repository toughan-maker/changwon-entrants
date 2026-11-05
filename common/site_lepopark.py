"""
창원 (창원레포츠파크 lepopark.or.kr) — 출주표 / 상담결과 / 경주결과 가져오기
"""
import re
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

from common import formats as F
from common.lepopark import (
    COUNSEL_URL, ENTRANT_FIX_URL, ENTRANT_UNFIX_URL, FINALRATE_URL, RESULT_URL,
    clean, fetch_html, find_seqtimes, first_race_date, main_value,
)
from common.result_parser import (
    build_tables, lepopark_races, parse_exacta, popularity_ranks, title_race,
)

TRACK = "창원"

# 예: "창원 01 경주 [우수] 출발 12:55"
RACE_TITLE_RE = re.compile(r"(창원|부산|광명)\s*(\d+)\s*경주\s*\[([^\]]*)\]\s*출발\s*(\d{1,2}:\d{2})")
KISU_AGE_RE = re.compile(r"(\d+)\s*기\s*(\d+)\s*세")


# ───────────────────────── 출주표 ─────────────────────────
def _find_table_after(heading, keyword):
    """경주 제목 다음에서 keyword가 들어간 첫 표 (다음 경주 제목 전까지)"""
    for el in heading.find_all_next(["h3", "table"]):
        if el.name == "h3" and el is not heading and RACE_TITLE_RE.search(el.get_text(" ", strip=True)):
            return None
        if el.name == "table" and keyword in el.get_text():
            return el
    return None


def _residual_points(table) -> dict:
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


def parse_entrant(html: str, date_arg: str, track: str = TRACK):
    """반환: (DataFrame, 회차정보 문자열 또는 None)"""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ")
    m = re.search(r"\((\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일\)", text)
    race_date = F.yy_mm_dd(*m.groups()) if m else F.yy_mm_dd(date_arg[:4], date_arg[4:6], date_arg[6:8])
    r = F.ROUND_RE.search(text)
    cols = F.ENTRANT_COLUMNS + ["잔여점수"]
    if not r:
        return pd.DataFrame(columns=cols), None
    year, round_no, day_no = r.group(1), f"{int(r.group(2)):02d}{r.group(3).upper()}", r.group(4)

    rows = []
    for heading in soup.find_all(["h2", "h3", "h4"]):
        hm = RACE_TITLE_RE.search(heading.get_text(" ", strip=True))
        if not hm or hm.group(1) != track:
            continue
        table = _find_table_after(heading, "기어")
        if table is None:
            continue
        residual = _residual_points(_find_table_after(heading, "잔여"))
        rid = F.race_id(track, year, round_no, day_no, hm.group(2))
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 17 or not tds[0].find("a", href=re.compile(r"/racer/")):
                continue
            first_text = tds[0].get_text(" ", strip=True)
            num = re.match(r"\s*(\d+)", first_text)
            ka = KISU_AGE_RE.search(first_text)
            no = num.group(1) if num else ""
            rows.append(F.entrant_row(
                track=track, race_no_id=rid, race_date=race_date, race_time=hm.group(4),
                grade=hm.group(3).strip(), player_no=no, name=tds[0].find("a").get_text(strip=True),
                kisu=ka.group(1) if ka else "", age=ka.group(2) if ka else "",
                gear=main_value(tds[1]), win=main_value(tds[4]), quinella=main_value(tds[5]),
                rec200=main_value(tds[2]), train=main_value(tds[3]),
                track_score=main_value(tds[14]), total_score=main_value(tds[15]),
                rank=main_value(tds[16]), residual=residual.get(no, ""),
            ))
    return pd.DataFrame(rows, columns=cols), F.round_label(year, round_no, day_no)


def load_entrant(race_day: date, fixed: bool):
    date_str = race_day.strftime("%Y%m%d")
    url = (ENTRANT_FIX_URL if fixed else ENTRANT_UNFIX_URL).format(date=date_str)
    df, label = parse_entrant(fetch_html(url), date_str)
    return df, label, url


# ───────────────────────── 상담결과 ─────────────────────────
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
            if len(tds) >= 14:
                players.append(F.counsel_values(tds[:14]))
    return year, times, seq, players


def counsel_url(seqtimes: str | None) -> str:
    return f"{COUNSEL_URL}?seqtimes={seqtimes}" if seqtimes else COUNSEL_URL


def load_counsel(year: str = "", times: str = "", seq: str = "", race_day: date | None = None) -> dict:
    """반환 dict: year, times, rdate(YYYY-MM-DD), players, url, seq, notes[]"""
    notes = []
    if not seq and year and times:
        seq = find_seqtimes(year, times)
        if not seq:
            raise ValueError(f"{year}년 {times}회차를 찾을 수 없습니다.")
    p_year, p_times, p_seq, players = parse_counsel(fetch_html(counsel_url(seq)))
    seq = seq or p_seq
    year, times = year or p_year, times or p_times
    if p_year and p_times and times.isdigit() and (year != p_year or int(times) != int(p_times)):
        notes.append(f"페이지 기준은 {p_year}년 {p_times}회차입니다. 입력값({year}년 {times}회차)으로 표기합니다.")
    if race_day:
        rdate = race_day.strftime("%Y-%m-%d")
    else:
        d = first_race_date(year, seq) if year else ""     # API 값은 YYYYMMDD
        rdate = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else ""
    return {"year": year, "times": times, "rdate": rdate, "players": players,
            "url": counsel_url(seq), "seq": seq, "notes": notes}


# ───────────────────────── 경주결과 ─────────────────────────
def load_result(race_day: date, year: str, round_no: str, track: str = TRACK) -> dict:
    """반환 dict: players_df, races_df, label, url, warnings[], page(년·회·일차)"""
    date_str = race_day.strftime("%Y%m%d")
    url = RESULT_URL.format(date=date_str)
    races, info = lepopark_races(fetch_html(url), track)
    warnings = []
    for r in races:
        seq = info["seqrace"].get(r["no"])
        r["ranks"] = {}
        if not seq:
            continue
        try:
            matrix, title = parse_exacta(fetch_html(FINALRATE_URL.format(date=date_str, seq=seq)))
        except requests.RequestException:
            continue
        # 다른 경주 페이지가 열린 경우를 막기 위해 경주번호 확인 (예: '창원06 [우수] 10:35')
        if title_race(title) == (track, r["no"]):
            r["ranks"] = popularity_ranks(matrix)
    if not info.get("day") and races:
        warnings.append("페이지에서 일차를 찾지 못해 01로 넣었습니다.")
    players_df, races_df = build_tables(races, track, year, round_no, info.get("day") or "01",
                                        race_day.strftime("%Y-%m-%d"))
    page = {"year": info.get("year", ""), "round": info.get("round", ""), "day": info.get("day", "")}
    return {"players_df": players_df, "races_df": races_df, "url": url,
            "warnings": warnings, "page": page}
