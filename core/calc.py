"""투자비·손익 계산 엔진. AI를 쓰지 않고 명시적 산식으로만 계산한다 (기획서 4.2, 4.3)."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass(frozen=True)
class PnLInput:
    annual_volume: float      # 연간 예상 판매량
    supply_price: float       # 공급단가 (단위당)
    unit_cost: float          # 단위당 공급원가
    annual_opex: float        # 추가 운영비 (유지관리비·운송비 등, 연간)
    investment: float         # 초기 투자비 합계


@dataclass(frozen=True)
class PnLResult:
    revenue: float
    cogs: float
    gross_profit: float
    gross_margin_pct: float
    contribution: float          # 영업기여이익
    contribution_margin_pct: float
    payback_years: float | None  # 회수 불가(순유입 <= 0)면 None
    investment: float

    def as_dict(self) -> dict:
        return asdict(self)


def item_amount(qty: float, unit_price: float) -> float:
    return round(float(qty) * float(unit_price))


def total_investment(items: Iterable[dict]) -> float:
    """items: {'qty', 'unit_price'} 목록. 금액 = 수량 × 단가."""
    return sum(item_amount(i.get("qty", 0) or 0, i.get("unit_price", 0) or 0) for i in items)


def investment_by_category(items: Iterable[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for i in items:
        cat = i.get("category") or "기타"
        out[cat] = out.get(cat, 0) + item_amount(i.get("qty", 0) or 0, i.get("unit_price", 0) or 0)
    return out


def compute_pnl(p: PnLInput) -> PnLResult:
    revenue = p.annual_volume * p.supply_price
    cogs = p.annual_volume * p.unit_cost
    gross = revenue - cogs
    contribution = gross - p.annual_opex
    payback = p.investment / contribution if contribution > 0 else None
    return PnLResult(
        revenue=revenue,
        cogs=cogs,
        gross_profit=gross,
        gross_margin_pct=(gross / revenue * 100) if revenue else 0.0,
        contribution=contribution,
        contribution_margin_pct=(contribution / revenue * 100) if revenue else 0.0,
        payback_years=payback,
        investment=p.investment,
    )


def simulate(base: PnLInput, price_deltas_pct: Iterable[float],
             investment_deltas_pct: Iterable[float]) -> list[dict]:
    """공급단가·투자비 변동률 격자 시뮬레이션. 각 조합의 손익 결과를 반환."""
    rows = []
    for pd_ in price_deltas_pct:
        for idl in investment_deltas_pct:
            p = PnLInput(
                annual_volume=base.annual_volume,
                supply_price=base.supply_price * (1 + pd_ / 100),
                unit_cost=base.unit_cost,
                annual_opex=base.annual_opex,
                investment=base.investment * (1 + idl / 100),
            )
            r = compute_pnl(p)
            rows.append({
                "공급단가 변동(%)": pd_,
                "투자비 변동(%)": idl,
                "공급단가": p.supply_price,
                "투자비": p.investment,
                "매출총이익": r.gross_profit,
                "영업기여이익": r.contribution,
                "기여이익률(%)": r.contribution_margin_pct,
                "회수기간(년)": r.payback_years,
            })
    return rows


def check_approval_criteria(r: PnLResult, max_payback_years: float, min_margin_pct: float) -> list[str]:
    """승인 기준 미달 사유 목록. 비어 있으면 기준 충족. (기준값은 회사 정책에 맞게 설정)"""
    issues = []
    if r.payback_years is None:
        issues.append("연간 영업기여이익이 0 이하여서 투자비를 회수할 수 없습니다.")
    elif r.payback_years > max_payback_years:
        issues.append(f"투자비 회수기간 {r.payback_years:.1f}년이 기준({max_payback_years:g}년)을 초과합니다.")
    if r.contribution_margin_pct < min_margin_pct:
        issues.append(f"영업기여이익률 {r.contribution_margin_pct:.1f}%가 기준({min_margin_pct:g}%) 미만입니다.")
    return issues
