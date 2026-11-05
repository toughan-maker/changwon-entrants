# 경륜 도구 (창원 · 광명 · 부산)

경기장별 출주표, 출전선수상담결과, 경주결과를 가져와 화면에 표로 보여주고 DB 업로드용 txt로 내려받는 Streamlit 웹앱입니다.
사이드바 메뉴는 경기장별(창원 / 광명 / 부산)로 묶여 있고, 각 경기장마다 같은 3개 메뉴가 있습니다.

| 경기장 | raceno 접두어 | 정보 출처 |
|---|---|---|
| 창원 | `c` | 창원레포츠파크 (lepopark.or.kr) |
| 광명 | `j` | KCYCLE (kcycle.or.kr) |
| 부산 | `b` | 스포원 (spo1.or.kr) |

- raceno 형식: 접두어 + 년도 + 회차(2자리) + 일차(2자리) + 경주번호(2자리) — 예: `c2026330301`, `j2026430301`, `b2026380301`
- 회차·일차는 각 경기장 사이트 기준 번호입니다. (같은 날이라도 경기장마다 회차 번호가 다름)
- 출력 형식(필드 순서, 200m·최종주회 기록 계산, 순위 없음 → 9, 인기순위 등)은 세 경기장 모두 같습니다.

## 폴더 구조
```
app.py                       메뉴 (경기장별 그룹)
apps/entrant.py              출주표 화면        ┐
apps/counsel.py              상담결과 화면      ├ render(경기장) 하나로 세 경기장 공용
apps/result.py               경주결과 화면      ┘
common/site_lepopark.py      창원 사이트에서 가져오기
common/site_kcycle.py        광명 사이트에서 가져오기
common/site_spo1.py          부산 사이트에서 가져오기
common/formats.py            출주표·상담결과 출력 형식
common/result_parser.py      경주결과 출력 형식·계산
common/tracks.py             경기장 설정 (이름, 접두어, 사이트 주소)
common/lepopark.py           페이지 요청(10분 캐시)·txt 변환 등 공통 함수
```

## 로컬 실행
```bash
pip install -r requirements.txt
streamlit run app.py
```

> `common/` 폴더의 파일이 바뀐 업데이트 뒤에 Streamlit Cloud에서 ImportError가 나면 **Manage app → ⋮ → Reboot app** 으로 재시작하세요.
