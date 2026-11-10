"""
DB 업로드 (카페24 MSSQL)

- 출주표   → chuljuRec  (키: raceNo + playerNumber)
- 상담결과 → councel    (키: racenoofweek + playerName)

공통 규칙
- 키가 같은 행이 있으면 UPDATE, 없으면 INSERT
- 전체를 한 트랜잭션으로 처리 → 중간에 오류가 나면 모두 취소(이전 상태 유지)
- 열 길이를 넘는 값은 잘라서 넣고 경고 (키 열은 자르지 않고 그 행을 건너뜀)
  · nvarchar: 글자 수 기준
  · varchar : 바이트 수 기준 (한글 1글자 = 2바이트, CP949)
- 표에 없는 DB 열은 건드리지 않음 (UPDATE 때 기존 값 유지)
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
    Col("description", "훈련내용", "vstr", 200),
    Col("traindate", "훈련일수", "int"),
    Col("kija_desc", "참고사항", "vstr", 300),
), "상담결과")

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


def to_records(df: pd.DataFrame, target: Target, label_cols=("경주번호", "회차")) -> tuple[list[dict], list[str]]:
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


def upsert(target: Target, rows: list[dict]) -> dict:
    """target 테이블에 반영 → {'inserted': n, 'updated': m}. 오류 시 전부 취소하고 예외 발생."""
    if not rows:
        return {"inserted": 0, "updated": 0}
    t, keys = target.table, list(target.keys)
    cols = [c.db for c in target.cols]
    sets = [c for c in cols if c not in keys]
    where = " AND ".join(f"[{k}] = %s" for k in keys)
    update_sql = f"UPDATE {t} SET " + ", ".join(f"[{c}] = %s" for c in sets) + f" WHERE {where}"
    insert_sql = (f"INSERT INTO {t} ({', '.join(f'[{c}]' for c in cols)}) "
                  f"VALUES ({', '.join(['%s'] * len(cols))})")

    first = keys[0]                       # 첫 번째 키(경주번호·회차)로 기존 행 조회
    firsts = sorted({r[first] for r in rows})
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT {', '.join(f'[{k}]' for k in keys)} FROM {t} WITH (UPDLOCK, HOLDLOCK) "
                        f"WHERE [{first}] IN ({', '.join(['%s'] * len(firsts))})", tuple(firsts))
            existing = {tuple(_norm_key(v) for v in row) for row in cur.fetchall()}
            ins = upd = 0
            for r in rows:
                key = tuple(_norm_key(r[k]) for k in keys)
                if key in existing:
                    cur.execute(update_sql, tuple(r[c] for c in sets) + tuple(r[k] for k in keys))
                    upd += 1
                else:
                    cur.execute(insert_sql, tuple(r[c] for c in cols))
                    ins += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"inserted": ins, "updated": upd}


# ── 출주표 화면에서 쓰는 이름 (하위 호환)
def chulju_records(df: pd.DataFrame):
    return to_records(df, CHULJU)


def upsert_chulju(rows: list[dict]) -> dict:
    return upsert(CHULJU, rows)
