"""
DB 업로드 (카페24 MSSQL)

- 출주표   → chuljuRec  (키: raceNo + playerNumber)
- 상담결과 → councel    (키: racenoofweek + playerName)
- 경주결과 → raceRec    (키: raceNo) + playerRec (키: raceNo + playerNumber), 한 트랜잭션

공통 규칙
- 키가 같은 행이 있으면 UPDATE, 없으면 INSERT
- 전체를 한 트랜잭션으로 처리 → 중간에 오류가 나면 모두 취소(이전 상태 유지)
- 열 길이를 넘는 값은 잘라서 넣고 경고 (키 열은 자르지 않고 그 행을 건너뜀)
  · nvarchar: 글자 수 기준
  · varchar : 바이트 수 기준 (한글 1글자 = 2바이트, CP949)
- 표에 없는 DB 열, insert_only 로 지정한 열은 UPDATE 때 건드리지 않음 (기존 값 유지)
"""
import re
from dataclasses import dataclass
from datetime import date

import pandas as pd

from common import db

VARCHAR_ENCODING = "cp949"   # 카페24 한국어 DB 의 varchar 저장 방식


@dataclass(frozen=True)
class Col:
    db: str          # DB 열 이름
    src: str         # DataFrame 열 이름
    kind: str        # str(nvarchar·글자수) / vstr(varchar·바이트수) / int / float / date
    size: int | None = None


@dataclass(frozen=True)
class Target:
    table: str
    keys: tuple[str, ...]
    cols: tuple[Col, ...]
    label: str
    insert_only: tuple[str, ...] = ()   # 새로 추가할 때만 넣고, 수정(UPDATE) 때는 기존 값 유지


CHULJU = Target("chuljuRec", ("raceNo", "playerNumber"), (
    Col("raceNo", "경주번호", "str", 11),
    Col("playDate", "경주일", "date"),
    Col("playTime", "경주시간", "str", 10),
    Col("playerNumber", "선수번호", "int"),
    Col("playerName", "선수명", "str", 10),
    Col("kisu", "기수", "int"),
    Col("age", "나이", "int"),
    Col("kia", "기어배수", "str", 10),
    Col("grade", "등급", "str", 10),
    Col("winPercent", "승률", "int"),
    Col("savePercent", "연대율", "int"),
    Col("rap200", "200미터기록", "str", 10),
    Col("training", "훈련지", "str", 20),
    Col("jamsilPoint", "경기장점수", "float"),
    Col("totPoint", "종합점수", "float"),
    Col("ground", "경기장", "str", 10),
    Col("money_rank", "상금순위", "int"),
    # 추가 파일 항목 (값1~3 은 파일과 같이 0, 잔여점수)
    Col("badpoint_2", "값1", "int"),
    Col("badpoint_1", "값2", "int"),
    Col("badpoint_n", "값3", "int"),
    Col("badpoint_r", "잔여점수", "int"),
), "출주표")

# 상담결과: 기수·전회출전은 넣지 않음, trainStatus·healthStatus·condition 은 건드리지 않음
#           훈련내용 → kija_desc, 참고사항 → description
#           kija_desc·description 은 새 행일 때만 넣고, 이미 있는 행을 수정할 때는 기존 값 유지
COUNSEL = Target("councel", ("racenoofweek", "playerName"), (
    Col("racenoofweek", "회차", "vstr", 7),
    Col("playdate", "경주일", "date"),
    Col("playerName", "성명", "vstr", 10),
    Col("curTrain", "훈련지", "vstr", 10),
    Col("withTrain", "훈련동참자", "vstr", 20),
    Col("interval200", "200미터", "int"),
    Col("interval300", "333미터", "int"),
    Col("interval500", "500미터", "int"),
    Col("outside", "도로", "int"),
    Col("pista", "트랙", "int"),
    Col("weight", "체중", "int"),
    Col("kija_desc", "훈련내용", "vstr", 300),
    Col("traindate", "훈련일수", "int"),
    Col("description", "참고사항", "vstr", 200),
), "상담결과", insert_only=("description", "kija_desc"))

# 경주결과 - 경주정보 (weather·totaltime·totalmin·rap333·pos_near1~3 은 건드리지 않음)
def _tr(name, ticket_src, rate_src, ticket_kind="str", size=None):
    return (Col(f"{name}Ticket", ticket_src, ticket_kind, size), Col(f"{name}Rate", rate_src, "float"))


RACE = Target("raceRec", ("raceNo",), (
    Col("playDate", "경주일자", "date"),
    Col("raceNo", "raceno", "str", 11),
    Col("grade", "경주등급", "str", 10),
    Col("ground", "경기장", "str", 10),
    *_tr("dan", "단승", "단승배당률", "int"),
    *_tr("resDan", "동착단승", "단승동착배당률", "int"),
    Col("yunTicket1", "연승1", "int"), Col("yunRate1", "연승1배당률", "float"),
    Col("yunTicket2", "연승2", "int"), Col("yunRate2", "연승2배당률", "float"),
    *_tr("resYun", "연승3", "연승3배당률", "int"),
    *_tr("ssang", "쌍승티켓", "쌍승배당률", "str", 10),
    *_tr("resSsang", "동착쌍승티켓", "동착쌍승배당률", "str", 10),
    *_tr("bok", "복승티켓", "복승배당률", "str", 10),
    *_tr("resBok", "동착복승티켓", "동착복승배당률", "str", 10),
    *_tr("samBok", "삼복승티켓", "삼복승배당률", "str", 15),
    *_tr("resSambok", "동착삼복승티켓", "동착삼복승배당률", "str", 15),
    *_tr("samSsang", "삼쌍승티켓", "삼쌍승배당률", "str", 15),
    *_tr("resSamSsang", "동착삼쌍승티켓", "동착삼쌍승배당률", "str", 15),
    *_tr("SsangBok", "쌍복승티켓", "쌍복승배당률", "str", 15),
    *_tr("resSsangBok", "동착쌍복승티켓", "동착쌍복승배당률", "str", 15),
), "경주정보")

# 경주결과 - 선수별 (playStyle 은 새 행일 때만, description·howplay·level2·giveup 은 건드리지 않음)
PLAYER = Target("playerRec", ("raceNo", "playerNumber"), (
    Col("raceNo", "raceno", "str", 11),
    Col("playerNumber", "선수번호", "int"),
    Col("playerName", "선수명", "str", 10),
    Col("ranking", "순위", "float"),
    Col("goalGap", "착차", "str", 10),
    Col("playTime", "주행시간", "str", 10),
    Col("playStyle", "승부수", "str", 10),
    Col("rap200", "200미터기록", "int"),
    Col("rap333", "최종주회기록", "int"),
    Col("disqualified", "실격", "int"),
    Col("warning", "경고", "int"),
    Col("softWarning", "주의", "int"),
    Col("giveupReason", "기권구분", "str", 50),
    Col("ground", "경기장", "str", 10),
    Col("playDate", "경주일자", "date"),
    Col("grade", "경주등급", "str", 10),
    Col("popularity", "인기순위", "int"),
), "선수별 경주결과", insert_only=("playStyle",))

# 하위 호환 (출주표 화면에서 쓰던 이름)
TABLE = CHULJU.table


def _conv(v, kind: str):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if s == "":
        return None
    if kind == "int":
        m = re.search(r"-?\d+", s)
        return int(m.group(0)) if m else None
    if kind == "float":
        try:
            return float(s)
        except ValueError:
            return None
    if kind == "date":   # '26-11-01' / '2026-11-01' → date
        m = re.match(r"(\d{2,4})-(\d{1,2})-(\d{1,2})", s)
        if not m:
            return None
        y = int(m.group(1))
        return date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(3)))
    return s


def _length(v: str, kind: str) -> int:
    if kind == "vstr":
        return len(v.encode(VARCHAR_ENCODING, errors="replace"))
    return len(v)


def _cut(v: str, kind: str, size: int) -> str:
    """size 에 맞게 자르기 (varchar 는 바이트 기준, 한글이 반으로 잘리지 않게)"""
    if kind != "vstr":
        return v[:size]
    out, n = "", 0
    for ch in v:
        w = len(ch.encode(VARCHAR_ENCODING, errors="replace"))
        if n + w > size:
            break
        out, n = out + ch, n + w
    return out


def to_records(df: pd.DataFrame, target: Target, label_cols=("경주번호", "회차", "raceno")) -> tuple[list[dict], list[str]]:
    """DataFrame → (DB 행 목록, 경고 목록)"""
    rows, warns = [], []
    name_col = next((c.src for c in target.cols if c.db.lower() == "playername"), None)
    for _, r in df.iterrows():
        where = " ".join(str(r.get(c)) for c in (*label_cols, name_col) if c and c in r)
        rec, skip = {}, False
        for c in target.cols:
            v = _conv(r.get(c.src), c.kind)
            if c.kind in ("str", "vstr") and v is not None and c.size and _length(v, c.kind) > c.size:
                unit = "바이트" if c.kind == "vstr" else "자"
                if c.db in target.keys:
                    warns.append(f"{where}: {c.db} '{v}' 가 {c.size}{unit}를 넘어 이 행은 올리지 않습니다.")
                    skip = True
                    break
                warns.append(f"{where}: {c.db} 가 {c.size}{unit}를 넘어 뒷부분을 잘랐습니다.")
                v = _cut(v, c.kind, c.size)
            rec[c.db] = v
        if skip:
            continue
        missing = [k for k in target.keys if rec.get(k) is None]
        if missing:
            warns.append(f"{where}: 키 값({', '.join(missing)})이 없어 건너뜁니다.")
            continue
        rows.append(rec)
    # 같은 키가 두 번 나오면 마지막 값만 사용
    uniq = {tuple(r[k] for k in target.keys): r for r in rows}
    if len(uniq) < len(rows):
        warns.append(f"같은 키가 겹친 {len(rows) - len(uniq)}행은 마지막 값만 올립니다.")
    return list(uniq.values()), warns


def _norm_key(v):
    return v.strip() if isinstance(v, str) else (int(v) if isinstance(v, (int, float)) else v)


def _write(cur, target: Target, rows: list[dict]) -> dict:
    """한 테이블 반영 (트랜잭션은 호출하는 쪽에서)"""
    if not rows:
        return {"inserted": 0, "updated": 0}
    t, keys = target.table, list(target.keys)
    cols = [c.db for c in target.cols]
    sets = [c for c in cols if c not in keys and c not in target.insert_only]
    where = " AND ".join(f"[{k}] = %s" for k in keys)
    update_sql = f"UPDATE {t} SET " + ", ".join(f"[{c}] = %s" for c in sets) + f" WHERE {where}"
    insert_sql = (f"INSERT INTO {t} ({', '.join(f'[{c}]' for c in cols)}) "
                  f"VALUES ({', '.join(['%s'] * len(cols))})")
    first = keys[0]                       # 첫 번째 키(경주번호·회차)로 기존 행 조회
    firsts = sorted({r[first] for r in rows})
    cur.execute(f"SELECT {', '.join(f'[{k}]' for k in keys)} FROM {t} WITH (UPDLOCK, HOLDLOCK) "
                f"WHERE [{first}] IN ({', '.join(['%s'] * len(firsts))})", tuple(firsts))
    existing = {tuple(_norm_key(v) for v in row) for row in cur.fetchall()}
    ins = upd = 0
    for r in rows:
        if tuple(_norm_key(r[k]) for k in keys) in existing:
            cur.execute(update_sql, tuple(r[c] for c in sets) + tuple(r[k] for k in keys))
            upd += 1
        else:
            cur.execute(insert_sql, tuple(r[c] for c in cols))
            ins += 1
    return {"inserted": ins, "updated": upd}


def upsert_many(jobs: list[tuple[Target, list[dict]]]) -> dict:
    """여러 테이블을 한 트랜잭션으로 반영 → {테이블: {'inserted', 'updated'}}.
    하나라도 오류가 나면 전부 취소하고 예외 발생."""
    out = {}
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            for target, rows in jobs:
                out[target.table] = _write(cur, target, rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return out


def upsert(target: Target, rows: list[dict]) -> dict:
    """한 테이블 반영 → {'inserted': n, 'updated': m}"""
    if not rows:
        return {"inserted": 0, "updated": 0}
    return upsert_many([(target, rows)])[target.table]


# ── 출주표 화면에서 쓰는 이름 (하위 호환)
def chulju_records(df: pd.DataFrame):
    return to_records(df, CHULJU)


def upsert_chulju(rows: list[dict]) -> dict:
    return upsert(CHULJU, rows)
