"""
짝수 달력 변경 (week_table) — Streamlit 없이 동작

week_table
    week_count      순서 (1~12, 고정)
    week_startdate  시작일 'YYYY-MM-DD' (varchar 10)
    week_enddate    종료일 'YYYY-MM-DD' (varchar 10)

- 추가·삭제 없이 순서별 시작일·종료일만 수정
- 순서 미루기: 1→2, 2→3 … 11→12, 12번 내용은 버리고 1번은 빈칸
"""
from datetime import date

import pandas as pd

from common import db

TABLE = "week_table"
ROWS = 12


def _to_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, date):
        return v
    d = pd.to_datetime(str(v).strip(), errors="coerce")
    return None if pd.isna(d) else d.date()


def load() -> tuple[pd.DataFrame, list[str]]:
    """→ (표[week_count, start, end], 주의 목록)"""
    _, rows = db.query(f"SELECT week_count, week_startdate, week_enddate FROM {TABLE} ORDER BY week_count")
    notes = []
    counts = [r[0] for r in rows]
    if len(rows) != ROWS or sorted(counts) != list(range(1, ROWS + 1)):
        notes.append(f"{TABLE} 에 순서가 1~{ROWS} 로 {ROWS}개 있어야 하는데, 지금은 {len(rows)}개입니다 "
                     f"(순서: {', '.join(str(c) for c in counts)}). 있는 행만 수정합니다.")
    df = pd.DataFrame([(int(r[0]), _to_date(r[1]), _to_date(r[2])) for r in rows if r[0] is not None],
                      columns=["week_count", "start", "end"])
    for r in rows:
        for v, label in ((r[1], "시작일"), (r[2], "종료일")):
            if v not in (None, "") and _to_date(v) is None:
                notes.append(f"순서 {r[0]} {label} '{v}' 는 날짜로 읽을 수 없어 빈칸으로 표시합니다.")
    return df, notes


def shift(df: pd.DataFrame) -> pd.DataFrame:
    """한 칸씩 뒤로 미루기 (마지막 내용은 버리고 첫 칸은 빈칸)"""
    out = df.copy().reset_index(drop=True)
    out[["start", "end"]] = df[["start", "end"]].shift(1).astype(object)
    out.loc[0, ["start", "end"]] = [None, None]
    out["start"] = out["start"].map(_to_date)
    out["end"] = out["end"].map(_to_date)
    return out


def check(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """→ (오류: 저장 안 함, 참고: 저장은 함)"""
    errors, notes = [], []
    for _, r in df.iterrows():
        s, e, n = _to_date(r["start"]), _to_date(r["end"]), int(r["week_count"])
        if s is None or e is None:
            errors.append(f"순서 {n}: 시작일과 종료일을 모두 입력해 주세요.")
        elif s > e:
            errors.append(f"순서 {n}: 시작일({s})이 종료일({e})보다 늦습니다.")
    dated = [(int(r["week_count"]), _to_date(r["start"])) for _, r in df.iterrows() if _to_date(r["start"])]
    for (n1, d1), (n2, d2) in zip(dated, dated[1:]):
        if d2 >= d1:
            notes.append(f"순서 {n2}({d2})가 순서 {n1}({d1})보다 최근 날짜입니다. 1번이 가장 최근이 되도록 되어 있는지 확인하세요.")
    return errors, notes


def save(df: pd.DataFrame) -> int:
    """순서별 UPDATE — 한 트랜잭션"""
    with db.connect() as conn:
        cur = conn.cursor()
        try:
            for _, r in df.iterrows():
                cur.execute(f"UPDATE {TABLE} SET week_startdate = %s, week_enddate = %s WHERE week_count = %s",
                            (_to_date(r["start"]).isoformat(), _to_date(r["end"]).isoformat(), int(r["week_count"])))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return len(df)
