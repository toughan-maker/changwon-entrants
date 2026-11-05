"""
경주결과 공통 처리 (Streamlit 없이 동작 → 단독 테스트 가능)

- 표 읽기 도우미: parse_info / parse_players / odds_from_cells / parse_exacta
- 결과 조립:      build_tables(races, ...) → (선수별 결과 DataFrame, 경주정보 DataFrame)
- 창원(lepopark): parse_result(html, year, round_no, ...)

경기장마다 페이지 모양은 달라도, 경주 하나를 아래 dict 로 만들어 build_tables 에 넘기면
출력 형식(필드 순서·기록 계산·순위 9 처리·배당 정리)은 모두 같아집니다.
    {"no": 1, "grade": "우수", "info": {"200m": '11"76', "최종주회": '19"40'},
     "players": [parse_players 결과], "odds": {"단승": [("4", "9.3")], ...},
     "ranks": {선수번호(int): 인기순위}}
"""
import re

import pandas as pd
from bs4 import BeautifulSoup

from common.tracks import TRACK_PREFIX

NO_RANK = "9"  # 낙차·실격 등으로 순위가 나오지 않은 선수의 순위 값

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

BET_TYPES = ["단승", "연승", "쌍승", "복승", "삼복승", "쌍복승", "삼쌍승"]

# 예: "창원06 경주 [확정]"
RACE_HEAD_RE = re.compile(r"(창원|부산|광명)\s*(\d{1,2})\s*경주")
# 최종배당률 페이지 제목: "창원06 [우수] 10:35", "광명 03경주 (선발 13 : 41)", "부산 01경주 (우수 11 : 02)"
TITLE_RE = re.compile(r"(창원|부산|광명)\s*(\d{1,2})\s*(?:경주|\[)")
# 예: "경주결과 2026년 33회 3일차", "2026년 부산 38회 3일차" (41A회 포함)
ROUND_RE = re.compile(r"(\d{4})\s*년\s*(?:[가-힣]+\s*)?(\d+)([A-Za-z]?)\s*회\s*(\d+)\s*일차")
DATE_RE = re.compile(r"\((\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\)")
# 창원·부산 표기 "4-6(119.9)" / 광명 표기 "(4-6)119.9"
TICKET_RE = re.compile(r"(\d+(?:\s*-\s*\d+)*)\s*\(\s*([\d.,]+)\s*\)")
TICKET_PAREN_FIRST_RE = re.compile(r"\(\s*(\d+(?:\s*-\s*\d+)*)\s*\)\s*([\d.,]+)")

HEAD_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
OTHER_TITLE_TAGS = {"strong", "p", "div", "span", "dt", "caption", "button", "li"}
EMPTY_MARKS = {"-", "－", "—"}


# ───────────────────────── 작은 도우미 ─────────────────────────
def _lines(cell) -> list[str]:
    """셀 안의 줄(<br> 기준) 목록"""
    return [s.strip() for s in cell.get_text("\n").replace("\xa0", " ").split("\n") if s.strip()]


def _text(cell) -> str:
    return " ".join(_lines(cell))


def _value(cell) -> str:
    """셀 값. '-' 만 있으면 빈칸으로 (광명 사이트는 빈칸을 '-' 로 표시)"""
    t = _text(cell)
    return "" if t in EMPTY_MARKS else t


def _key(text: str) -> str:
    """표 제목 비교용: 공백 제거, 200M → 200m"""
    return re.sub(r"\s+", "", text).replace("M", "m")


def time_to_sec(t: str):
    """주행시간 '2:25:6850' / '2:29.9910' → 초. 못 읽으면 None"""
    m = re.match(r"^\s*(\d+)\s*:\s*(\d{1,2})\s*[:.]\s*(\d+)\s*$", t or "")
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2)) + float("0." + m.group(3))


def normalize_time(t: str) -> str:
    """주행시간을 창원 표기로 통일: '2:29.9910' → '2:29:9910'"""
    m = re.match(r"^\s*(\d+)\s*:\s*(\d{1,2})\s*[:.]\s*(\d+)\s*$", t or "")
    return f"{m.group(1)}:{m.group(2)}:{m.group(3)}" if m else (t or "").strip()


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


def parse_tickets(text: str) -> list[tuple[str, str]]:
    """'1-4(47.5) 4-1(149.6)' 또는 '(1-4)47.5(4-1)149.6' → [('1-4','47.5'), ('4-1','149.6')]"""
    regex = TICKET_PAREN_FIRST_RE if re.match(r"\s*\(", text) else TICKET_RE
    return [(re.sub(r"\s+", "", m.group(1)), m.group(2).replace(",", ""))
            for m in regex.finditer(text)]


def odds_from_cells(cells) -> dict:
    """결과 요약표 한 줄의 배당 칸 7개(단승~삼쌍승) → {'단승': [(티켓, 배당)], ...}"""
    return {name: parse_tickets("\n".join(_lines(c))) for name, c in zip(BET_TYPES, cells)}


def _pick(items, i):
    return items[i] if len(items) > i else ("", "")


def _rows(table) -> list[list]:
    return [tr.find_all(["th", "td"]) for tr in table.find_all("tr")]


# ───────────────────────── 표 읽기 (공통) ─────────────────────────
def parse_info(table) -> dict:
    """경주정보 표 → {'등급': '우수', '200m': '11"76', '최종주회': '19"40', ...}"""
    rows = _rows(table)
    for i, row in enumerate(rows):
        heads = [_key(_text(c)) for c in row]
        if "최종주회" in heads and i + 1 < len(rows):
            vals = [_value(c) for c in rows[i + 1]]
            return {h: (vals[j] if j < len(vals) else "") for j, h in enumerate(heads)}
    return {}


def parse_players(table) -> list[dict]:
    """선수별 결과 표 → [{'선수번호', '선수명', '순위', ...}]
    번호가 이름 칸에 같이 있거나('1 김원호') 따로 '번호' 칸에 있어도 처리합니다."""
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

    idx = {k: col(k) for k in ["번호", "선수명", "순위", "착차", "주행시간", "승부수",
                                "실격", "경고", "주의", "기권"]}
    out = []
    for row in rows[head_idx + 1:]:
        if not row:
            continue

        def v(k):
            j = idx[k]
            return _value(row[j]) if j is not None and j < len(row) else ""

        if idx["번호"] is not None:
            num, name = v("번호"), v("선수명")
        else:
            m = re.match(r"^(\d+)\s*(.*)$", v("선수명") if idx["선수명"] is not None else _text(row[0]))
            num, name = (m.group(1), m.group(2)) if m else ("", "")
        if not num.isdigit():
            continue

        rank = v("순위")
        if not rank.isdigit():
            rank = NO_RANK  # 낙차·실격 등으로 순위가 없는 경우

        out.append({
            "선수번호": num,
            "선수명": name.strip(),
            "순위": rank, "착차": v("착차"), "주행시간": normalize_time(v("주행시간")),
            "승부수": re.sub(r"\s+", "", v("승부수")),  # '추 입' → '추입'
            "실격": v("실격"), "경고": v("경고"), "주의": v("주의"), "기권구분": v("기권"),
        })
    return out


def _table_label(table) -> str:
    """표 이름: caption → thead 첫 줄 → 바로 앞 제목(h2~h5, strong) 순으로 찾음"""
    if table.caption and _text(table.caption):
        return _text(table.caption)
    if table.thead:
        first = table.thead.find("tr")
        if first and "식" in _text(first):        # 예: '쌍승식' (머리줄이 '선 \ 후 1 2 …' 면 건너뜀)
            return _text(first)
    prev = table.find_previous(["h2", "h3", "h4", "h5", "strong"])
    return _text(prev) if prev else ""


def parse_exacta(html: str) -> tuple[dict, str]:
    """최종배당률 페이지의 쌍승식 표 → ({1착번호: {2착번호: 배당}}, 페이지의 경주 제목)
    창원·부산(caption), 광명(앞 제목) 모두 처리. 표 모양: 행=1착, 열=2착."""
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    for h in soup.find_all(["h2", "h3", "h4", "td"]):
        t = h.get_text(" ", strip=True)
        if TITLE_RE.search(t) and len(t) < 60:
            title = t
            break
    table = None
    for t in soup.find_all("table"):
        label = _key(_table_label(t))
        if "쌍승식" in label and "쌍복" not in label:
            table = t
            break
    if table is None:
        return {}, title

    cols, matrix = [], {}
    for row in _rows(table):
        cells = [_text(c) for c in row]
        if not cells:
            continue
        if not cols:
            # 머리줄: 첫 칸은 '배번' / '선 \ 후' 같은 글자, 나머지는 번호
            if not cells[0].isdigit() and len(cells) > 2 and all(c.isdigit() for c in cells[1:]):
                cols = [int(c) for c in cells[1:]]
            continue
        if not cells[0].isdigit():
            continue
        first = int(cells[0])
        r = {}
        for j, v in enumerate(cells[1:]):
            if j < len(cols) and cols[j] != first:
                try:
                    r[cols[j]] = float(v.replace(",", ""))
                except ValueError:
                    pass  # 빈칸(결장 등)
        matrix[first] = r
    return matrix, title


def title_race(title: str):
    """'창원06 [우수] 10:35' / '광명 03경주 (선발 13 : 41)' → ('창원', 6). 못 읽으면 None"""
    m = TITLE_RE.search(title or "")
    return (m.group(1), int(m.group(2))) if m else None


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


# ───────────────────────── 결과 조립 (공통) ─────────────────────────
def make_raceno(track: str, year: str, round_no: str, day: str, race_no: int) -> str:
    rnd = str(round_no).strip().upper()
    if rnd.isdigit():
        rnd = f"{int(rnd):02d}"
    return f"{TRACK_PREFIX[track]}{year}{rnd}{int(day):02d}{int(race_no):02d}"


def build_tables(races: list[dict], track: str, year: str, round_no: str, day: str,
                 race_date: str):
    """경주 dict 목록 → (선수별 결과 DataFrame, 경주정보 DataFrame). raceno 순으로 정렬."""
    players_out, races_out = [], []
    for race in races:
        players = race["players"]
        info, odds = race.get("info", {}), race.get("odds", {})
        ranks = race.get("ranks") or {}
        raceno = make_raceno(track, year, round_no, day, race["no"])
        grade = race.get("grade") or info.get("등급", "")
        rec200 = record_to_sec(info.get("200m", ""))
        last_lap = record_to_sec(info.get("최종주회", ""))

        # 1위 주행시간 (동착이면 같은 시간). 1위 시간이 없으면 가장 빠른 시간.
        times = {p["선수번호"]: time_to_sec(p["주행시간"]) for p in players}
        firsts = [times[p["선수번호"]] for p in players
                  if p["순위"] == "1" and times[p["선수번호"]] is not None]
        valid = [x for x in times.values() if x is not None]
        base = min(firsts) if firsts else (min(valid) if valid else None)

        for p in players:
            tm = times[p["선수번호"]]
            diff = (tm - base) if (tm is not None and base is not None) else None
            pop = ranks.get(int(p["선수번호"]))
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
                "인기순위": str(pop) if pop else "",
            })

        # 배당 정리
        rank = {p["선수번호"]: int(p["순위"]) for p in players}
        win = odds.get("단승", [])
        place = odds.get("연승", [])
        place = sorted(place, key=lambda x: (rank.get(x[0], 99), place.index(x)))
        quin = [(sort_ticket(a), b) for a, b in odds.get("복승", [])]
        trio = [(sort_ticket(a), b) for a, b in odds.get("삼복승", [])]

        row = {"경주일자": race_date, "raceno": raceno, "경주등급": grade, "경기장": track}
        row["단승"], row["단승배당률"] = _pick(win, 0)
        row["동착단승"], row["단승동착배당률"] = _pick(win, 1)
        for i in range(3):
            row[f"연승{i + 1}"], row[f"연승{i + 1}배당률"] = _pick(place, i)
        for name, items in [("쌍승", odds.get("쌍승", [])), ("복승", quin), ("삼복승", trio),
                            ("쌍복승", odds.get("쌍복승", [])), ("삼쌍승", odds.get("삼쌍승", []))]:
            row[f"{name}티켓"], row[f"{name}배당률"] = _pick(items, 0)
            row[f"동착{name}티켓"], row[f"동착{name}배당률"] = _pick(items, 1)
        races_out.append(row)

    players_df = pd.DataFrame(players_out, columns=PLAYER_COLUMNS)
    races_df = pd.DataFrame(races_out, columns=RACE_COLUMNS)
    if not races_df.empty:
        order = {r: i for i, r in enumerate(sorted(races_df["raceno"]))}
        races_df = races_df.sort_values("raceno", kind="stable").reset_index(drop=True)
        players_df = (players_df.assign(_o=players_df["raceno"].map(order))
                      .sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True))
    return players_df, races_df


# ───────────────────────── 창원 (lepopark) ─────────────────────────
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


def parse_odds(table) -> dict:
    """창원 경주별 배당 표 → {'단승': [('4','9.3')], '연승': [...], ...}"""
    rows = _rows(table)
    for i, row in enumerate(rows):
        heads = [_key(_text(c)) for c in row]
        if "단승" in heads:
            for data in rows[i + 1:]:
                if len(data) >= 2:
                    return {h: parse_tickets("\n".join(_lines(data[j])))
                            for j, h in enumerate(heads) if j < len(data)}
    return {}


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


def lepopark_races(html: str, track: str = "창원") -> tuple[list[dict], dict]:
    """창원레포츠파크 결과 페이지 → (경주 dict 목록, 페이지 정보 + seqrace)"""
    soup = BeautifulSoup(html, "html.parser")
    info = page_header(soup)
    seq_map = race_seq_map(soup)
    info["seqrace"] = {}  # {경주번호: seqrace} → 최종배당률 페이지 조회용
    races = []
    for race in split_races(soup):
        if race["track"] != track:
            continue
        t = _classify(race["tables"])
        if "result" not in t:
            continue
        races.append({
            "no": race["no"],
            "info": parse_info(t["info"]) if "info" in t else {},
            "players": parse_players(t["result"]),
            "odds": parse_odds(t["odds"]) if "odds" in t else {},
        })
        if race["key"] in seq_map:
            info["seqrace"][race["no"]] = seq_map[race["key"]]
    return races, info


def parse_result(html: str, year: str, round_no: str, race_date: str = "",
                 track: str = "창원", ranks_by_no: dict | None = None):
    """창원 결과 페이지 → (선수별 결과, 경주정보, 페이지 정보). race_date: 'YYYY-MM-DD'"""
    races, info = lepopark_races(html, track)
    for r in races:
        r["ranks"] = (ranks_by_no or {}).get(r["no"], {})
    players_df, races_df = build_tables(races, track, year, round_no, info["day"] or "01",
                                        race_date or info["date"])
    return players_df, races_df, info
