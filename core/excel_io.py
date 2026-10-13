"""기존 공사 견적서(Excel)에서 항목·수량·단가를 추출한다.

헤더명을 유연하게 매칭하고, 결과는 항상 담당자가 화면에서 확인·수정한다.
"""
from __future__ import annotations

import io

import pandas as pd

_ALIASES = {
    "name": ["항목", "품명", "품목", "공사명", "공종", "내역", "명칭", "name", "item"],
    "qty": ["수량", "qty", "quantity"],
    "unit_price": ["단가", "unit_price", "unitprice", "가격"],
    "amount": ["금액", "합계", "공급가액", "amount", "total"],
    "category": ["구분", "분류", "카테고리", "category"],
}
CATEGORIES = ["저장탱크·부대설비", "배관공사", "설치·시공", "기타"]


def _match(col) -> str | None:
    c = str(col).strip().lower().replace(" ", "")
    for key, names in _ALIASES.items():
        if any(n in c for n in names):
            return key
    return None


def parse_quote(file_bytes: bytes) -> pd.DataFrame:
    """견적서에서 항목을 추출. 헤더 행은 앞 20행 중 가장 많이 매칭되는 행으로 판단."""
    raw = pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=object)
    best_row, best_score = 0, -1
    for r in range(min(20, len(raw))):
        score = len({m for m in (_match(v) for v in raw.iloc[r].dropna()) if m})
        if score > best_score:
            best_row, best_score = r, score
    header = [_match(v) if pd.notna(v) else None for v in raw.iloc[best_row]]
    body = raw.iloc[best_row + 1:].reset_index(drop=True)
    out = pd.DataFrame()
    for idx, key in enumerate(header):
        if key and key not in out.columns:
            out[key] = body.iloc[:, idx]
    if "name" not in out.columns:
        raise ValueError("항목명(품명/공사명 등) 열을 찾지 못했습니다. 견적서 헤더를 확인하세요.")
    for col in ("qty", "unit_price", "amount"):
        out[col] = pd.to_numeric(out[col], errors="coerce") if col in out.columns else float("nan")
    out = out[out["name"].notna()]
    out = out[~out["name"].astype(str).str.contains("합계|소계|총계", na=False)].copy()
    # 수량이 없으면 1, 단가가 없고 금액만 있으면 금액÷수량으로 역산
    qty = out["qty"].fillna(1).replace(0, 1)
    out["qty"] = qty
    out["unit_price"] = out["unit_price"].fillna(out["amount"] / qty).fillna(0)
    if "category" not in out.columns:
        out["category"] = "기타"
    out["category"] = out["category"].fillna("기타").astype(str)
    out["source"] = "견적서 추출"
    return out[["category", "name", "qty", "unit_price", "source"]].reset_index(drop=True)
