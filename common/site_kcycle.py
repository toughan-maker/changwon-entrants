"""
광명 (KCYCLE kcycle.or.kr) — 출주표 / 상담결과 / 경주결과 가져오기

주소 형식 (년도/회차/일차는 광명 사이트 기준 번호)
    출주표   /race/card/decision/2026/43/3   (미확정: /race/card/undecided/...)
    상담결과 /race/state/racerinterview/2026/43
    경주결과 /race/result/general/2026/43/3            ← 요약표(배당)
             /race/result/general/2026/43/3/001/01     ← 경주별 상세 (001 = 광명)
    최종배당 /race/dividendrate/final/2026/43/3/001/01
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

TRACK = "광명"
BASE = TRACKS[TRACK].site
MEET_CD = "001"  # 광명

# 예: "광명 01경주 (선발 12:55)", "광명 16경주 (특선결승 18 : 54)"
TITLE_RE = re.compile(r"(광명|부산|창원)\s*(\d+)\s*경주\s*\(\s*([^()]*?)\s+(\d{1,2}\s*:\s*\d{2})\s*\)")
# 일차 선택 목록: "(43회 3일) 11월 01일 (일요일)"
DAY_OPTION_RE = re.compile(r"\((\d+)\s*회\s*(\d+)\s*일\)\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _t(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ")).strip() if el is not None else ""


def _selected(soup, name):
    sel = soup.find("select", attrs={"name": name})
    if sel is None:
        return None
    return sel.find("option", selected=True) or sel.find("option")


# ───────────────────────── 날짜 → 회차·일차 ─────────────────────────
def find_tms_day(path: str, race_day: date):
    """광명 사이트 선택 목록에서 경주일에 해당하는 (회차, 일차) 찾기. 못 찾으면 None.
    path 예: '/race/card/decision', '/race/result/general'"""
    want = (race_day.month, race_day.day)
    for url in (f"{BASE}{path}", f"{BASE}{path}/{race_day.year}/1/1"):
        try:
            soup = BeautifulSoup(fetch_html(url), "html.parser")
        except requests.RequestException:
            continue
        y = _selected(soup, "stndYear")
        if y is not None and y.get("value", "").strip() != str(race_day.year):
            continue
        sel = soup.find("select", attrs={"name": "tmsDayOrd"})
        for opt in (sel.find_all("option") if sel else []):
            m = DAY_OPTION_RE.search(opt.get_text(" "))
            if m and (int(m.group(3)), int(m.group(4))) == want:
                return int(m.group(1)), int(m.group(2))
    return None


# ───────────────────────── 출주표 ─────────────────────────
def parse_entrant(html: str, year: str, track: str = TRACK):
    soup = BeautifulSoup(html, "html.parser")
    cols = F.ENTRANT_COLUMNS + ["잔여점수"]
    opt = _selected(soup, "tmsDayOrd")
    m = DAY_OPTION_RE.search(opt.get_text(" ")) if opt is not None else None
    if not m:
        return pd.DataFrame(columns=cols), None
    round_no, day_no = m.group(1), m.group(2)
    race_date = F.yy_mm_dd(year, m.group(3), m.group(4))

    rows = []
    for sec in soup.select("div.cptLinkSection"):
        tm = TITLE_RE.search(_t(sec.find(["h2", "h3"])))
        if not tm or tm.group(1) != track:
            continue
        rid = F.race_id(track, year, round_no, day_no, tm.group(2))
        entry = penalty = None
        for t in sec.find_all("table"):
            head = _t(t.thead)
            if entry is None and "기어배수" in head:
                entry = t
            elif penalty is None and "잔여점수" in head:
                penalty = t
        if entry is None:
            continue

        residual = {}
        for tr in (penalty.select("tbody tr") if penalty else []):
            sign = tr.select_one("span.sign")
            tds = tr.find_all("td")
            if sign and tds:
                residual[_t(sign)] = _t(tds[-1])

        for tr in entry.select("tbody tr"):
            sign, tds = tr.select_one("span.sign"), tr.find_all("td")
            if sign is None or len(tds) < 14:
                continue
            no = _t(sign)
            other = _t(tr.select_one(".other"))           # '10기/49세'
            ka = re.search(r"(\d+)\s*기\s*/?\s*(\d+)\s*세", other)
            score = _t(tds[12])                           # '(광명) 86.90 (종합) 87.46'
            ts = re.search(rf"\({track}\)\s*([\d.]+)", score)
            tot = re.search(r"\(종합\)\s*([\d.]+)", score)
            rows.append(F.entrant_row(
                track=track, race_no_id=rid, race_date=race_date,
                race_time=re.sub(r"\s+", "", tm.group(4)), grade=tm.group(3).strip(),
                player_no=no, name=_t(tr.select_one("a.player")),
                kisu=ka.group(1) if ka else "", age=ka.group(2) if ka else "",
                gear=_t(tds[0]), rec200=_t(tds[1]), train=_t(tds[2]),
                win=_t(tds[3]), quinella=_t(tds[4]),
                track_score=ts.group(1) if ts else "", total_score=tot.group(1) if tot else "",
                rank=_t(tds[13]), residual=residual.get(no, ""),
            ))
    return pd.DataFrame(rows, columns=cols), F.round_label(year, round_no, day_no)


def load_entrant(race_day: date, fixed: bool):
    kind = "decision" if fixed else "undecided"
    found = find_tms_day(f"/race/card/{kind}", race_day)
    if found is None:
        return pd.DataFrame(columns=F.ENTRANT_COLUMNS + ["잔여점수"]), None, f"{BASE}/race/card/{kind}"
    url = f"{BASE}/race/card/{kind}/{race_day.year}/{found[0]}/{found[1]}"
    df, label = parse_entrant(fetch_html(url), str(race_day.year))
    return df, label, url


# ───────────────────────── 상담결과 ─────────────────────────
def parse_counsel(html: str, year: str):
    """→ (회차, 첫 경주일 YYYY-MM-DD, 선수행 리스트)"""
    soup = BeautifulSoup(html, "html.parser")
    opt = _selected(soup, "tms")
    times = opt.get("value", "").strip() if opt is not None else ""
    d = re.search(r"\((\d{1,2})\s*월\s*(\d{1,2})\s*일", opt.get_text(" ")) if opt is not None else None
    rdate = f"{year}-{int(d.group(1)):02d}-{int(d.group(2)):02d}" if d else ""
    players = []
    for tr in soup.select("table tbody tr"):
        th, tds = tr.find("th"), tr.find_all("td")
        if th is None or len(tds) < 12:
            continue
        nm = re.match(r"\s*(.+?)\s*/\s*(\d+)\s*기", _t(th))    # '김민호/25기'
        if not nm:
            continue
        players.append(F.counsel_values([nm.group(1), nm.group(2)] + [_t(td) for td in tds[:12]]))
    return times, rdate, players


def load_counsel(year: str, times: str, race_day: date | None = None) -> dict:
    url = f"{BASE}/race/state/racerinterview/{year}/{int(times)}"
    p_times, rdate, players = parse_counsel(fetch_html(url), year)
    notes = []
    if p_times and int(p_times) != int(times):
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


def parse_summary(html: str, track: str = TRACK) -> dict:
    """결과 요약표 → {경주번호: 배당 dict}"""
    soup = BeautifulSoup(html, "html.parser")
    table = _table_with(soup, "경주", "단승식", "삼쌍승식")
    out = {}
    for tr in (table.select("tbody tr") if table else []):
        th, tds = tr.find("th"), tr.find_all("td")
        m = re.match(rf"\s*{track}\s*(\d+)", _t(th)) if th else None
        if m and len(tds) >= 10:
            out[int(m.group(1))] = odds_from_cells(tds[3:10])
    return out


def parse_race_page(html: str) -> dict:
    """경주별 상세 → {'title', 'grade', 'info', 'players'}"""
    soup = BeautifulSoup(html, "html.parser")
    h = soup.select_one(".comTitH2 h2") or soup.find("h2", string=TITLE_RE)
    title = _t(h)
    tm = TITLE_RE.search(title)
    info_t = _table_with(soup, "최종주회")
    players_t = _table_with(soup, "순위", "주행시간")
    return {"title": title, "grade": tm.group(3).strip() if tm else "",
            "info": parse_info(info_t) if info_t is not None else {},
            "players": parse_players(players_t) if players_t is not None else []}


def load_result(race_day: date, year: str, round_no: str, track: str = TRACK) -> dict:
    warnings = []
    found = find_tms_day("/race/result/general", race_day)
    empty = {"players_df": build_tables([], track, year, round_no, "1", "")[0],
             "races_df": build_tables([], track, year, round_no, "1", "")[1],
             "url": f"{BASE}/race/result/general", "warnings": warnings, "page": {}}
    if found is None:
        return empty
    tms, day = found
    y = race_day.year
    url = f"{BASE}/race/result/general/{y}/{tms}/{day}"
    summary = parse_summary(fetch_html(url), track)
    empty["url"] = url

    races = []
    for no in sorted(summary):
        try:
            page = parse_race_page(fetch_html(f"{url}/{MEET_CD}/{no:02d}"))
        except requests.RequestException:
            warnings.append(f"{track} {no}경주 상세 결과를 가져오지 못했습니다.")
            continue
        if title_race(page["title"]) != (track, no) or not page["players"]:
            warnings.append(f"{track} {no}경주 상세 결과를 찾지 못했습니다.")
            continue
        ranks = {}
        try:
            matrix, title = parse_exacta(fetch_html(
                f"{BASE}/race/dividendrate/final/{y}/{tms}/{day}/{MEET_CD}/{no:02d}"))
            if title_race(title) == (track, no):
                ranks = popularity_ranks(matrix)
        except requests.RequestException:
            pass
        races.append({"no": no, "grade": page["grade"], "info": page["info"],
                      "players": page["players"], "odds": summary[no], "ranks": ranks})

    players_df, races_df = build_tables(races, track, year, round_no, str(day),
                                        race_day.strftime("%Y-%m-%d"))
    return {"players_df": players_df, "races_df": races_df, "url": url, "warnings": warnings,
            "page": {"year": str(y), "round": f"{tms:02d}", "day": f"{day:02d}"}}
