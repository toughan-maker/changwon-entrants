"""
부산 (스포원 spo1.or.kr) — 출주표 / 상담결과 / 경주결과 가져오기

주소 형식 (회차는 부산 사이트 기준 번호)
    출주표   /race/raceInfoList.do?RACEYY=2026&RACEDATE=20261101   (미확정: raceInfoNonList.do)
    상담결과 /race/raceAdvice.do?RACEYY_TIMES=2026_38
    경주결과 /race/raceResult.do?RACEYY=2026&RACEDATE=20261101               ← 요약표(배당)
             /race/raceResult.do?SEQRACE=156155&RACEYY=2026&RACEDATE=20261101&gubun=Y  ← 경주별
    최종배당 /race/raceLastRate.do?RACEDATE=20261101&SEQRACE=156155
"""
import re
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

from common import formats as F
from common.lepopark import fetch_html
from common.result_parser import (
    build_tables, odds_from_cells, parse_exacta, parse_info, parse_players,
    popularity_ranks, title_race,
)
from common.tracks import TRACKS

TRACK = "부산"
BASE = TRACKS[TRACK].site

# 예: "부산 06경주 (우수) 5주회 1691m 출발 10:35"
TITLE_RE = re.compile(r"(부산|광명|창원)\s*(\d+)\s*경주\s*\(([^)]*)\).*?출발\s*(\d{1,2}\s*:\s*\d{2})")
# 예: "2026년 부산 38회 3일차 (11월 01일)"
HEAD_RE = re.compile(r"(\d{4})\s*년\s*[가-힣]*\s*(\d+)\s*회\s*(\d+)\s*일차\s*\(\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _t(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ")).strip() if el is not None else ""


def _page_head(soup):
    """→ (년도, 회차, 일차, 월, 일) 또는 None"""
    for h in soup.find_all(["h2", "h3"]):
        m = HEAD_RE.search(_t(h))
        if m:
            return tuple(int(x) for x in m.groups())
    return None


# ───────────────────────── 출주표 ─────────────────────────
def parse_entrant(html: str, race_day: date | None = None, track: str = TRACK):
    soup = BeautifulSoup(html, "html.parser")
    cols = F.ENTRANT_COLUMNS + ["잔여점수"]
    head = _page_head(soup)
    if head is None:
        return pd.DataFrame(columns=cols), None
    year, round_no, day_no, mon, dd = head
    if race_day and (mon, dd) != (race_day.month, race_day.day):
        return pd.DataFrame(columns=cols), None      # 요청한 날짜가 아닌 페이지
    race_date = F.yy_mm_dd(year, mon, dd)

    rows = []
    for h in soup.select("h3.record_title"):
        tm = TITLE_RE.search(_t(h))
        if not tm or tm.group(1) != track:
            continue
        rid = F.race_id(track, str(year), round_no, day_no, tm.group(2))
        entry = penalty = None
        for el in h.find_all_next(["h3", "table"]):
            if el.name == "h3":
                if "record_title" in (el.get("class") or []):
                    break
                continue
            head_txt = _t(el.thead)
            if entry is None and "기어" in head_txt:
                entry = el
            elif penalty is None and "잔여점수" in head_txt:
                penalty = el
        if entry is None:
            continue

        residual = {}
        for tr in (penalty.select("tbody tr") if penalty else []):
            tds = tr.find_all("td")
            if len(tds) > 2:
                residual[_t(tds[0])] = _t(tds[-1])

        for tr in entry.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 20 or not _t(tds[0]).isdigit():
                continue
            no = _t(tds[0])
            rows.append(F.entrant_row(
                track=track, race_no_id=rid, race_date=race_date,
                race_time=re.sub(r"\s+", "", tm.group(4)), grade=tm.group(3).strip(),
                player_no=no, name=_t(tds[1]), kisu=_t(tds[2]), age=_t(tds[3]),
                gear=_t(tds[4]), rec200=_t(tds[5]), train=_t(tds[6]),
                win=_t(tds[7]), quinella=_t(tds[8]),
                track_score=_t(tds[17]), total_score=_t(tds[18]), rank=_t(tds[19]),
                residual=residual.get(no, ""),
            ))
    return pd.DataFrame(rows, columns=cols), F.round_label(year, round_no, day_no)


def load_entrant(race_day: date, fixed: bool):
    page = "raceInfoList.do" if fixed else "raceInfoNonList.do"
    url = f"{BASE}/race/{page}?RACEYY={race_day.year}&RACEDATE={race_day:%Y%m%d}"
    df, label = parse_entrant(fetch_html(url), race_day)
    return df, label, url


# ───────────────────────── 상담결과 ─────────────────────────
def parse_counsel(html: str, year: str):
    """→ (회차, 첫 경주일 YYYY-MM-DD, 선수행 리스트)"""
    soup = BeautifulSoup(html, "html.parser")
    sel = soup.find("select", attrs={"name": "RACETIMES"})
    opt = (sel.find("option", selected=True) if sel else None)
    times = opt.get("value", "").strip() if opt is not None else ""
    rd = soup.find("input", id="rcdate")
    d = re.match(r"\s*(\d{1,2})\.(\d{1,2})", rd.get("value", "")) if rd is not None else None
    rdate = f"{year}-{int(d.group(1)):02d}-{int(d.group(2)):02d}" if d else ""
    players = []
    for table in soup.find_all("table"):
        if "상담" not in _t(table.caption):
            continue
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) >= 14:
                players.append(F.counsel_values([_t(td) for td in tds[:14]]))
    return times, rdate, players


def load_counsel(year: str, times: str, race_day: date | None = None) -> dict:
    url = f"{BASE}/race/raceAdvice.do?RACEYY_TIMES={year}_{int(times)}"
    p_times, rdate, players = parse_counsel(fetch_html(url), year)
    notes = []
    if p_times and p_times.isdigit() and int(p_times) != int(times):
        notes.append(f"페이지 기준은 {p_times}회차입니다. 입력값({year}년 {times}회차)으로 표기합니다.")
    if race_day:
        rdate = race_day.strftime("%Y-%m-%d")
    return {"year": year, "times": times, "rdate": rdate, "players": players,
            "url": url, "seq": "", "notes": notes}


# ───────────────────────── 경주결과 ─────────────────────────
def _table_with(soup, *words):
    for t in soup.find_all("table"):
        head = re.sub(r"\s+", "", _t(t.thead) or _t(t.find("tr")))
        if all(w in head for w in words):
            return t
    return None


def parse_summary(html: str, track: str = TRACK):
    """결과 요약표 → (페이지 머리 정보, {경주번호: (SEQRACE, 배당 dict)})"""
    soup = BeautifulSoup(html, "html.parser")
    table = _table_with(soup, "경주구분", "단승", "삼쌍승")
    out = {}
    for tr in (table.select("tbody tr") if table else []):
        tds = tr.find_all("td")
        if len(tds) < 11:
            continue
        m = re.match(rf"\s*{track}\s*(\d+)\s*경주", _t(tds[0]))
        a = tds[0].find("a", href=re.compile(r"SEQRACE=\d+"))
        if m and a:
            seq = re.search(r"SEQRACE=(\d+)", a["href"]).group(1)
            out[int(m.group(1))] = (seq, odds_from_cells(tds[4:11]))
    return _page_head(soup), out


def load_result(race_day: date, year: str, round_no: str, track: str = TRACK) -> dict:
    warnings = []
    ymd = race_day.strftime("%Y%m%d")
    url = f"{BASE}/race/raceResult.do?RACEYY={race_day.year}&RACEDATE={ymd}"
    head, summary = parse_summary(fetch_html(url), track)
    if head is None or (head[3], head[4]) != (race_day.month, race_day.day):
        summary = {}                                  # 요청한 날짜가 아닌 페이지
    day = head[2] if head else 1

    races = []
    for no in sorted(summary):
        seq, odds = summary[no]
        try:
            soup = BeautifulSoup(fetch_html(
                f"{BASE}/race/raceResult.do?SEQRACE={seq}&RACEYY={race_day.year}&RACEDATE={ymd}&gubun=Y"),
                "html.parser")
        except requests.RequestException:
            warnings.append(f"{track} {no}경주 상세 결과를 가져오지 못했습니다.")
            continue
        info_t = _table_with(soup, "등급", "최종주회")
        players_t = _table_with(soup, "순위", "주행시간")
        players = parse_players(players_t) if players_t is not None else []
        if not players:
            warnings.append(f"{track} {no}경주 상세 결과를 찾지 못했습니다.")
            continue
        ranks = {}
        try:
            matrix, title = parse_exacta(fetch_html(
                f"{BASE}/race/raceLastRate.do?RACEDATE={ymd}&SEQRACE={seq}"))
            if title_race(title) == (track, no):
                ranks = popularity_ranks(matrix)
        except requests.RequestException:
            pass
        races.append({"no": no, "info": parse_info(info_t) if info_t is not None else {},
                      "players": players, "odds": odds, "ranks": ranks})

    players_df, races_df = build_tables(races, track, year, round_no, str(day), race_day.strftime("%Y-%m-%d"))
    page = {"year": str(head[0]), "round": f"{head[1]:02d}", "day": f"{head[2]:02d}"} if head else {}
    return {"players_df": players_df, "races_df": races_df, "url": url,
            "warnings": warnings, "page": page}
