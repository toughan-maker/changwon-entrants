"""
창원레포츠파크 경주결과 페이지 파서 (Streamlit 없이 동작 → 단독 테스트 가능)

    from common.result_parser import parse_result
    players_df, races_df, page_info = parse_result(html, year="2026", round_no="33")

- players_df : 선수별 경주결과 (PLAYER_COLUMNS 순서)
- races_df   : 경주정보/배당 (RACE_COLUMNS 순서)
- page_info  : 페이지 제목에서 읽은 {"year", "round", "day", "date"}
"""
import re

import pandas as pd
from bs4 import BeautifulSoup

TRACK_PREFIX = {"창원": "c", "부산": "b", "광명": "g"}

PLAYER_COLUMNS = [
    "raceno", "선수번호", "선수명", "순위", "착차", "주행시간", "승부수",
    "200미터기록", "최종주회기록", "실격", "경고", "주의", "기권구분",
    "경기장", "경주일자", "경주등급", "인기순위",
]

RACE_COLUMNS = [
    "경주일자", "raceno", "경주등급", "경기장",
    "단승", "단승배당률", "동착단승", "단승동착배당률",
    "연승1", "연승1배당률", "연승2", "연승2배당률", "연승3", "연승3배당률",
    "쌍승티켓", "쌍승배당률", "동착쌍승티켓", "동착쌍승배당률",
    "복승티켓", "복승배당률", "동착복승티켓", "동착복승배당률",
    "삼복승티켓", "삼복승배당률", "동착삼복승티켓", "동착삼복승배당률",
    "쌍복승티켓", "쌍복승배당률", "동착쌍복승티켓", "동착쌍복승배당률",
    "삼쌍승티켓", "삼쌍승배당률", "동착삼쌍승티켓", "동착삼쌍승배당률",
]

# 예: "창원06 경주 [확정]"
RACE_HEAD_RE = re.compile(r"(창원|부산|광명)\s*(\d{1,2})\s*경주")
# 예: "경주결과 2026년 33회 3일차" (41A회 포함)
ROUND_RE = re.compile(r"(\d{4})\s*년\s*(\d+)([A-Za-z]?)\s*회\s*(\d+)\s*일차")
DATE_RE = re.compile(r"\((\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\)")
# 예: "4-6(119.9)", "1-4-6(1,067.7)"
TICKET_RE = re.compile(r"(\d+(?:\s*-\s*\d+)*)\s*\(\s*([\d.,]+)\s*\)")

HEAD_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
OTHER_TITLE_TAGS = {"strong", "p", "div", "span", "dt", "caption", "button", "li"}


# ───────────────────────── 작은 도우미 ─────────────────────────
def _lines(cell) -> list[str]:
    """셀 안의 줄(<br> 기준) 목록"""
    return [s.strip() for s in cell.get_text("\n").replace("\xa0", " ").split("\n") if s.strip()]


def _text(cell) -> str:
    return " ".join(_lines(cell))


def _key(text: str) -> str:
    """표 제목 비교용: 공백 제거"""
    return re.sub(r"\s+", "", text)


def time_to_sec(t: str):
    """주행시간 '2:25:6850' → 145.685 (분:초:소수). 못 읽으면 None"""
    m = re.match(r"^\s*(\d+)\s*:\s*(\d{1,2})\s*[:.]\s*(\d+)\s*$", t or "")
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2)) + float("0." + m.group(3))


def record_to_sec(t: str):
    """구간기록 '11"76' / '11.76' / '11”76' → 11.76. 못 읽으면 None"""
    m = re.match(r"^\s*(\d+)\D+(\d+)\s*$", t or "")
    return float(f"{m.group(1)}.{m.group(2)}") if m else None


def format_record(sec) -> str:
    """11.7615 → '1176' (소수 둘째 자리 반올림 후 구분자 없이)"""
    if sec is None:
        return ""
    return f"{sec:.2f}".replace(".", "")


def sort_ticket(ticket: str) -> str:
    """'6-5-1' → '1-5-6' (복승·삼복승: 순위 상관없이 낮은 번호 먼저)"""
    nums = [int(n) for n in re.findall(r"\d+", ticket)]
    return "-".join(str(n) for n in sorted(nums))


def _tickets(lines: list[str]) -> list[tuple[str, str]]:
    """['1-4(47.5)', '4-1(149.6)'] → [('1-4','47.5'), ('4-1','149.6')]"""
    out = []
    for m in TICKET_RE.finditer("\n".join(lines)):
        out.append((re.sub(r"\s+", "", m.group(1)), m.group(2).replace(",", "")))
    return out


def _pick(items, i):
    return items[i] if len(items) > i else ("", "")


# ───────────────────────── 페이지 구조 ─────────────────────────
def page_header(soup) -> dict:
    text = soup.get_text(" ")
    info = {"year": "", "round": "", "day": "", "date": ""}
    m = ROUND_RE.search(text)
    if m:
        info.update(year=m.group(1), round=f"{int(m.group(2)):02d}{m.group(3).upper()}",
                    day=f"{int(m.group(4)):02d}")
    d = DATE_RE.search(text)
    if d:
        info["date"] = f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}"
    return info


def split_races(soup) -> list[dict]:
    """문서 순서대로 훑으며 경주 제목('창원06 경주') 아래의 표들을 묶습니다."""
    races, cur = [], None
    for el in soup.find_all(True):
        if el.name == "table":
            if cur is not None:
                cur["tables"].append(el)
            continue
        if el.name in HEAD_TAGS or el.name in OTHER_TITLE_TAGS:
            if el.find("table") is not None:
                continue
            txt = el.get_text(" ", strip=True)
            if len(txt) > 40:
                continue
            m = RACE_HEAD_RE.search(txt)
            if not m:
                continue
            key = (m.group(1), int(m.group(2)))
            if cur is not None and cur["key"] == key:
                continue  # 같은 제목을 감싼 태그가 여러 겹인 경우
            cur = {"key": key, "track": key[0], "no": key[1], "tables": []}
            races.append(cur)
    return races


def _rows(table) -> list[list]:
    return [tr.find_all(["th", "td"]) for tr in table.find_all("tr")]


def _classify(tables) -> dict:
    found = {}
    for t in tables:
        k = _key(t.get_text(" "))
        if "info" not in found and "최종주회" in k and "등급" in k:
            found["info"] = t
        elif "result" not in found and "주행시간" in k and "순위" in k:
            found["result"] = t
        elif "odds" not in found and "단승" in k and "삼쌍승" in k:
            found["odds"] = t
    return found


def parse_info(table) -> dict:
    """{'등급': '우수', '200m': '11"76', '최종주회': '19"40', ...}"""
    rows = _rows(table)
    for i, row in enumerate(rows):
        heads = [_key(_text(c)) for c in row]
        if "등급" in heads and i + 1 < len(rows):
            vals = [_text(c) for c in rows[i + 1]]
            return {h: (vals[j] if j < len(vals) else "") for j, h in enumerate(heads)}
    return {}


def parse_players(table) -> list[dict]:
    rows = _rows(table)
    head_idx, heads = None, []
    for i, row in enumerate(rows):
        hs = [_key(_text(c)) for c in row]
        if "순위" in hs and "주행시간" in hs:
            head_idx, heads = i, hs
            break
    if head_idx is None:
        return []

    def col(name_part):
        for j, h in enumerate(heads):
            if h.startswith(name_part):
                return j
        return None

    idx = {k: col(k) for k in ["선수명", "순위", "착차", "주행시간", "승부수",
                                "실격", "경고", "주의", "기권"]}
    out = []
    for row in rows[head_idx + 1:]:
        if not row:
            continue
        first = _text(row[0 if idx["선수명"] is None else idx["선수명"]])
        m = re.match(r"^(\d+)\s*(.*)$", first)
        if not m:
            continue

        def v(k):
            j = idx[k]
            return _text(row[j]) if j is not None and j < len(row) else ""

        out.append({
            "선수번호": m.group(1),
            "선수명": m.group(2).strip(),
            "순위": v("순위"), "착차": v("착차"), "주행시간": v("주행시간"),
            "승부수": v("승부수"), "실격": v("실격"), "경고": v("경고"),
            "주의": v("주의"), "기권구분": v("기권"),
        })
    return out


def parse_odds(table) -> dict:
    """{'단승': [('4','9.3')], '연승': [('4','8.9'), ('6','2.2')], ...}"""
    rows = _rows(table)
    for i, row in enumerate(rows):
        heads = [_key(_text(c)) for c in row]
        if "단승" in heads:
            for data in rows[i + 1:]:
                if len(data) >= 2:
                    return {h: _tickets(_lines(data[j]))
                            for j, h in enumerate(heads) if j < len(data)}
    return {}


# ───────────────────────── 인기순위 (최종배당률) ─────────────────────────
def race_seq_map(soup) -> dict:
    """결과 페이지 링크 <a href="#158328">창원06</a> → {('창원', 6): '158328'}"""
    out = {}
    for a in soup.find_all("a", href=re.compile(r"^#\d+$")):
        m = re.fullmatch(r"(창원|부산|광명|창|부|광)\s*(\d{1,2})", a.get_text(strip=True))
        if not m:
            continue
        track = {"창": "창원", "부": "부산", "광": "광명"}.get(m.group(1), m.group(1))
        out.setdefault((track, int(m.group(2))), a["href"][1:])
    return out


def parse_exacta(html: str) -> tuple[dict, str]:
    """최종배당률 페이지의 쌍승식 표 → ({1착번호: {2착번호: 배당}}, 경주제목)"""
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    h3 = soup.find("h3")
    if h3:
        title = h3.get_text(" ", strip=True)
    table = None
    for t in soup.find_all("table"):
        cap = _key(t.caption.get_text()) if t.caption else ""
        head = _key(t.thead.get_text()) if t.thead else ""
        if ("쌍승식" in cap or head.startswith("쌍승식")) and "쌍복" not in cap + head:
            table = t
            break
    if table is None:
        return {}, title
    cols = []
    for tr in table.find_all("tr"):
        cells = [_text(c) for c in tr.find_all(["th", "td"])]
        if cells and cells[0] == "배번":
            cols = [int(c) for c in cells[1:] if c.isdigit()]
            break
    matrix = {}
    for tr in (table.tbody or table).find_all("tr"):
        cells = [_text(c) for c in tr.find_all("td")]
        if not cells or not cells[0].isdigit():
            continue
        first = int(cells[0])
        row = {}
        for j, v in enumerate(cells[1:]):
            if j < len(cols) and cols[j] != first:
                try:
                    row[cols[j]] = float(v.replace(",", ""))
                except ValueError:
                    pass  # 빈칸(결장 등)
        matrix[first] = row
    return matrix, title


def popularity_ranks(matrix: dict) -> dict:
    """쌍승 최저배당 조합의 1착·2착 번호가 인기 1·2위,
    나머지는 1위 선수가 1착인 쌍승배당이 낮은 순서로 3위부터.
    배당이 같으면 배번이 낮은 선수가 앞. 배당이 없는 선수는 순위 없음."""
    pairs = [(odd, a, b) for a, row in matrix.items() for b, odd in row.items()]
    if not pairs:
        return {}
    _, first, second = min(pairs)
    ranks = {first: 1, second: 2}
    rest = sorted((odd, b) for b, odd in matrix.get(first, {}).items() if b not in ranks)
    for i, (_, b) in enumerate(rest, start=3):
        ranks[b] = i
    return ranks


# ───────────────────────── 메인 ─────────────────────────
def make_raceno(track: str, year: str, round_no: str, day: str, race_no: int) -> str:
    rnd = str(round_no).strip().upper()
    if rnd.isdigit():
        rnd = f"{int(rnd):02d}"
    return f"{TRACK_PREFIX[track]}{year}{rnd}{int(day):02d}{race_no:02d}"


def parse_result(html: str, year: str, round_no: str, race_date: str = "",
                 track: str = "창원"):
    """race_date: 'YYYY-MM-DD' (비우면 페이지에서 읽음)"""
    soup = BeautifulSoup(html, "html.parser")
    info = page_header(soup)
    race_date = race_date or info["date"]
    day = info["day"] or "01"

    seq_map = race_seq_map(soup)
    info["seqrace"] = {}  # {raceno: seqrace} → 최종배당률 페이지 조회용
    players_out, races_out = [], []
    for race in split_races(soup):
        if race["track"] != track:
            continue
        t = _classify(race["tables"])
        if "result" not in t:
            continue
        rinfo = parse_info(t["info"]) if "info" in t else {}
        players = parse_players(t["result"])
        odds = parse_odds(t["odds"]) if "odds" in t else {}

        raceno = make_raceno(track, year, round_no, day, race["no"])
        if race["key"] in seq_map:
            info["seqrace"][raceno] = seq_map[race["key"]]
        grade = rinfo.get("등급", "")
        rec200 = record_to_sec(rinfo.get("200m", ""))
        last_lap = record_to_sec(rinfo.get("최종주회", ""))

        # 1위 주행시간 (동착이면 같은 시간). 1위 시간이 없으면 가장 빠른 시간.
        times = {p["선수번호"]: time_to_sec(p["주행시간"]) for p in players}
        firsts = [times[p["선수번호"]] for p in players
                  if p["순위"].strip() == "1" and times[p["선수번호"]] is not None]
        valid = [x for x in times.values() if x is not None]
        base = min(firsts) if firsts else (min(valid) if valid else None)

        for p in players:
            tm = times[p["선수번호"]]
            diff = (tm - base) if (tm is not None and base is not None) else None
            players_out.append({
                "raceno": raceno, **{k: p[k] for k in
                                     ["선수번호", "선수명", "순위", "착차", "주행시간", "승부수"]},
                "200미터기록": format_record(rec200 + diff)
                if (rec200 is not None and diff is not None) else "",
                "최종주회기록": format_record(last_lap + diff)
                if (last_lap is not None and diff is not None) else "",
                "실격": p["실격"], "경고": p["경고"], "주의": p["주의"],
                "기권구분": p["기권구분"],
                "경기장": track, "경주일자": race_date, "경주등급": grade,
                "인기순위": "",
            })

        # 배당 정리
        rank = {p["선수번호"]: (int(p["순위"]) if p["순위"].strip().isdigit() else 99)
                for p in players}
        win = odds.get("단승", [])
        place = odds.get("연승", [])
        place = sorted(place, key=lambda x: (rank.get(x[0], 99), place.index(x)))
        exacta = odds.get("쌍승", [])
        quin = [(sort_ticket(a), b) for a, b in odds.get("복승", [])]
        trio = [(sort_ticket(a), b) for a, b in odds.get("삼복승", [])]
        ssb = odds.get("쌍복승", [])
        tri = odds.get("삼쌍승", [])

        row = {"경주일자": race_date, "raceno": raceno, "경주등급": grade, "경기장": track}
        row["단승"], row["단승배당률"] = _pick(win, 0)
        row["동착단승"], row["단승동착배당률"] = _pick(win, 1)
        for i in range(3):
            row[f"연승{i + 1}"], row[f"연승{i + 1}배당률"] = _pick(place, i)
        for name, items in [("쌍승", exacta), ("복승", quin), ("삼복승", trio),
                            ("쌍복승", ssb), ("삼쌍승", tri)]:
            row[f"{name}티켓"], row[f"{name}배당률"] = _pick(items, 0)
            row[f"동착{name}티켓"], row[f"동착{name}배당률"] = _pick(items, 1)
        races_out.append(row)

    players_df = pd.DataFrame(players_out, columns=PLAYER_COLUMNS)
    races_df = pd.DataFrame(races_out, columns=RACE_COLUMNS)
    if not races_df.empty:
        order = races_df["raceno"].tolist()
        races_df = races_df.sort_values("raceno", kind="stable").reset_index(drop=True)
        players_df["_o"] = players_df["raceno"].map({r: i for i, r in enumerate(sorted(order))})
        players_df = players_df.sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True)
    return players_df, races_df, info
