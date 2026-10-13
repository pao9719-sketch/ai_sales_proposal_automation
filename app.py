"""MS가스 신규 영업 제안 솔루션 - Streamlit MVP (기획서 1단계).

실행: streamlit run app.py
"""
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from core import db
from core.ai import draft_opinion
from core.calc import (PnLInput, check_approval_criteria, compute_pnl, investment_by_category,
                       item_amount, simulate, total_investment)
from core.excel_io import CATEGORIES, parse_quote
from core.proposal import build_external_proposal, build_internal_review

st.set_page_config(page_title="AI 신규 영업 제안 솔루션", layout="wide")
UPLOAD_DIR = db.DATA_DIR / "uploads"
FILE_KINDS = ["공사 견적서", "손익 계산서", "공장 도면", "기존 공급 제안서", "기타"]


def won(v) -> str:
    return "-" if v is None else f"{v:,.0f}원"


def safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-가-힣]", "_", Path(name).name)


def pnl_input(p: dict, items: list[dict]) -> PnLInput:
    return PnLInput(p["annual_volume"], p["supply_price"], p["unit_cost"], p["annual_opex"],
                    total_investment(items))


# ---------- 사이드바 ----------
st.sidebar.title("신규 영업 건")
actor = st.sidebar.text_input("담당자명", value=st.session_state.get("actor", ""), placeholder="이름 입력")
st.session_state["actor"] = actor
who = actor.strip() or "(미입력)"

st.sidebar.divider()
st.sidebar.subheader("승인 기준 (정책에 맞게 조정)")
max_payback = st.sidebar.number_input("최대 회수기간(년)", 0.5, 30.0, 5.0, 0.5)
min_margin = st.sidebar.number_input("최소 영업기여이익률(%)", 0.0, 100.0, 10.0, 1.0)

projects = db.list_projects()
with st.sidebar.expander("➕ 새 영업 건 등록", expanded=not projects):
    with st.form("new_project", clear_on_submit=True):
        n_name = st.text_input("건명")
        n_cust = st.text_input("고객사명")
        if st.form_submit_button("등록") and n_name and n_cust:
            new_id = db.create_project(n_name, n_cust, who)
            st.session_state["pid"] = new_id
            st.rerun()

if not projects:
    st.title("AI 기반 신규 영업 제안 및 손익 검토 자동화")
    st.info("왼쪽에서 새 영업 건을 등록하세요.")
    st.stop()

ids = [p["id"] for p in projects]
labels = {p["id"]: f"[{p['status']}] {p['name']} - {p['customer']}" for p in projects}
default = ids.index(st.session_state["pid"]) if st.session_state.get("pid") in ids else 0
pid = st.sidebar.selectbox("영업 건 선택", ids, index=default, format_func=labels.get)
st.session_state["pid"] = pid

proj = db.get_project(pid)
items = db.get_items(pid)
locked = proj["status"] in ("검토요청", "승인")

st.title(proj["name"])
st.caption(f"고객사: {proj['customer']}  |  상태: **{proj['status']}**")
if not actor.strip():
    st.warning("사이드바에 담당자명을 입력하면 변경 이력에 기록됩니다.")
if locked:
    st.info("검토 요청/승인 상태에서는 입력이 잠깁니다. 수정하려면 '검토·승인' 탭에서 반려 또는 재작성 처리하세요.")

tabs = st.tabs(["1 기본정보", "2 자료 업로드", "3 투자비", "4 손익 분석", "5 시뮬레이션", "6 검토·승인", "7 제안서"])

# ---------- 1 기본정보 ----------
with tabs[0]:
    with st.form("basic"):
        c1, c2 = st.columns(2)
        name = c1.text_input("건명", proj["name"], disabled=locked)
        customer = c2.text_input("고객사명", proj["customer"], disabled=locked)
        contact = c1.text_input("고객사 담당자/연락처", proj["contact"], disabled=locked)
        gas = c2.text_input("가스 종류 (예: 액체질소, 액체산소, 아르곤)", proj["gas"], disabled=locked)
        volume = c1.number_input("연간 예상 사용량", 0.0, value=float(proj["annual_volume"]), step=1000.0, disabled=locked)
        unit = c2.text_input("사용량 단위", proj["unit"], disabled=locked)
        price = c1.number_input("공급단가 (원/단위)", 0.0, value=float(proj["supply_price"]), step=10.0, disabled=locked)
        cost = c2.number_input("단위당 공급원가 (원)", 0.0, value=float(proj["unit_cost"]), step=10.0, disabled=locked)
        opex = c1.number_input("추가 운영비 (원/년: 유지관리·운송 등)", 0.0, value=float(proj["annual_opex"]),
                               step=100000.0, disabled=locked)
        years = c2.number_input("공급 기간(년)", 1, 30, int(proj["contract_years"]), disabled=locked)
        note = st.text_area("현장 메모 (설치 조건, 도면 확인사항 등)", proj["site_note"], disabled=locked)
        if st.form_submit_button("저장", disabled=locked):
            db.update_project(pid, who, name=name, customer=customer, contact=contact, gas=gas,
                              annual_volume=volume, unit=unit, supply_price=price, unit_cost=cost,
                              annual_opex=opex, contract_years=int(years), site_note=note)
            st.rerun()

# ---------- 2 자료 업로드 ----------
with tabs[1]:
    st.write("견적서·도면·손익 계산서·기존 제안서를 업로드합니다. 파일은 이 PC의 `data/uploads`에만 저장되며 외부로 전송되지 않습니다.")
    kind = st.selectbox("자료 유형", FILE_KINDS)
    up = st.file_uploader("파일 선택", type=["xlsx", "xls", "pdf", "png", "jpg", "jpeg", "docx", "hwp", "dwg", "dxf"],
                          disabled=locked)
    if up and st.button("업로드 저장", disabled=locked):
        folder = UPLOAD_DIR / str(pid)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{datetime.now():%Y%m%d%H%M%S}_{safe_name(up.name)}"
        dest.write_bytes(up.getvalue())
        db.add_file(pid, kind, up.name, str(dest), who)
        st.success(f"저장했습니다: {up.name}")
        st.rerun()
    files = db.get_files(pid)
    if files:
        st.dataframe(pd.DataFrame(files)[["kind", "filename", "uploaded_at"]].rename(
            columns={"kind": "유형", "filename": "파일명", "uploaded_at": "업로드 일시"}), use_container_width=True)

# ---------- 3 투자비 ----------
with tabs[2]:
    st.write("견적서(Excel)에서 항목을 추출하거나 직접 입력합니다. **금액 = 수량 × 단가**이며 AI가 아닌 산식으로 계산합니다.")
    quote = st.file_uploader("견적서 Excel에서 항목 추출 (항목/수량/단가/금액 헤더 인식)", type=["xlsx", "xls"],
                             key="quote_up", disabled=locked)
    if quote and st.button("항목 추출 후 아래 표에 추가", disabled=locked):
        try:
            extracted = parse_quote(quote.getvalue()).to_dict("records")
            db.save_items(pid, who, items + extracted)
            st.success(f"{len(extracted)}개 항목을 추가했습니다. 아래 표에서 확인·수정하세요.")
            st.rerun()
        except Exception as e:
            st.error(f"추출 실패: {e}")

    df = pd.DataFrame(items or [], columns=["category", "name", "qty", "unit_price", "source"])
    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True, disabled=locked, key=f"items_{pid}",
        column_config={
            "category": st.column_config.SelectboxColumn("구분", options=CATEGORIES, default="기타"),
            "name": st.column_config.TextColumn("항목", required=True),
            "qty": st.column_config.NumberColumn("수량", min_value=0, default=1),
            "unit_price": st.column_config.NumberColumn("단가(원)", min_value=0, default=0, format="%d"),
            "source": st.column_config.TextColumn("출처", disabled=True, default="수동"),
        })
    clean = [r for r in edited.fillna({"qty": 0, "unit_price": 0}).to_dict("records") if r.get("name")]
    if st.button("투자비 항목 저장", disabled=locked):
        db.save_items(pid, who, clean)
        st.rerun()
    st.metric("투자비 합계", won(total_investment(clean)))
    cats = investment_by_category(clean)
    if cats:
        st.bar_chart(pd.Series(cats, name="금액"))

# ---------- 4 손익 분석 ----------
base = pnl_input(proj, items)
res = compute_pnl(base)
with tabs[3]:
    if base.annual_volume <= 0 or base.supply_price <= 0:
        st.warning("기본정보에서 연간 사용량과 공급단가를 입력하세요.")
    c = st.columns(4)
    c[0].metric("예상 매출액(연)", won(res.revenue))
    c[1].metric("매출총이익(연)", won(res.gross_profit), f"{res.gross_margin_pct:.1f}%")
    c[2].metric("영업기여이익(연)", won(res.contribution), f"{res.contribution_margin_pct:.1f}%")
    c[3].metric("투자비 회수기간", "회수 불가" if res.payback_years is None else f"{res.payback_years:.1f}년")
    st.dataframe(pd.DataFrame([
        ["예상 매출액", "판매량 × 공급단가", won(res.revenue)],
        ["예상 매출원가", "판매량 × 단위당 공급원가", won(res.cogs)],
        ["예상 매출총이익", "매출액 − 매출원가", won(res.gross_profit)],
        ["예상 영업기여이익", "매출총이익 − 추가 운영비", won(res.contribution)],
        ["투자비", "투자비 항목 합계", won(res.investment)],
        ["투자비 회수기간", "투자비 ÷ 연간 영업기여이익", "회수 불가" if res.payback_years is None
         else f"{res.payback_years:.2f}년"],
    ], columns=["항목", "산식", "결과"]), use_container_width=True, hide_index=True)
    st.caption("산식은 기획 단계 예시입니다. 감가상각·유지관리비·운송비·투자 승인 기준은 실제 원가 체계에 맞춰 core/calc.py를 수정하세요.")

# ---------- 5 시뮬레이션 ----------
with tabs[4]:
    st.write("공급단가와 투자비를 변동시켜 수익성을 비교합니다. (저장되지 않는 가상 시나리오)")
    c1, c2 = st.columns(2)
    p_range = c1.slider("공급단가 변동 범위(%)", -30, 30, (-10, 10), 5)
    i_range = c2.slider("투자비 변동 범위(%)", -30, 30, (-10, 10), 5)
    p_steps = list(range(p_range[0], p_range[1] + 1, 5))
    i_steps = list(range(i_range[0], i_range[1] + 1, 5))
    sim = pd.DataFrame(simulate(base, p_steps, i_steps))
    if not sim.empty:
        pivot = sim.pivot(index="공급단가 변동(%)", columns="투자비 변동(%)", values="회수기간(년)")
        st.subheader("투자비 회수기간(년) — 행: 공급단가 변동, 열: 투자비 변동")
        st.dataframe(pivot.style.format("{:.1f}", na_rep="회수 불가"), use_container_width=True)
        pivot2 = sim.pivot(index="공급단가 변동(%)", columns="투자비 변동(%)", values="영업기여이익")
        st.subheader("연간 영업기여이익(원)")
        st.dataframe(pivot2.style.format("{:,.0f}"), use_container_width=True)
        with st.expander("전체 결과 표"):
            st.dataframe(sim, use_container_width=True)

        st.subheader("현재 조건에 반영")
        new_price = st.number_input("공급단가 조정값(원)", 0.0, value=float(proj["supply_price"]), step=10.0)
        if st.button("공급단가 적용", disabled=locked):
            db.update_project(pid, who, supply_price=new_price)
            st.rerun()

# ---------- 6 검토·승인 ----------
issues = check_approval_criteria(res, max_payback, min_margin)
with tabs[5]:
    st.subheader("승인 기준 검토")
    if issues:
        for s in issues:
            st.error(s)
    else:
        st.success("설정된 승인 기준을 모두 충족합니다.")
    if not items:
        st.warning("투자비 항목이 없습니다. 승인 전에 투자비를 입력하세요.")

    status = proj["status"]
    c1, c2, c3 = st.columns(3)
    if status in ("작성중", "반려"):
        if c1.button("검토 요청", type="primary", disabled=not items):
            db.set_status(pid, who, "검토요청", "; ".join(issues))
            st.rerun()
    if status == "검토요청":
        comment = st.text_input("검토 의견")
        if c1.button("승인", type="primary"):
            snap = {
                "project": {k: proj[k] for k in ("name", "customer", "gas", "annual_volume", "unit",
                                                 "supply_price", "unit_cost", "annual_opex",
                                                 "contract_years", "site_note")},
                "items": items,
                "pnl": res.as_dict(),
                "issues": issues,
                "approved_by": who,
                "approved_at": datetime.now().isoformat(timespec="seconds"),
            }
            db.set_status(pid, who, "승인", comment, snapshot=snap)
            st.rerun()
        if c2.button("반려"):
            db.set_status(pid, who, "반려", comment)
            st.rerun()
    if status == "승인":
        if c1.button("승인 취소 후 재작성"):
            db.set_status(pid, who, "작성중", "승인 취소")
            st.rerun()
    st.caption("※ 승인 시 당시의 조건·투자비·손익이 스냅샷으로 고정되며, 제안서는 이 스냅샷으로만 생성됩니다.")
    st.subheader("변경 이력")
    audit = db.get_audit(pid)
    if audit:
        st.dataframe(pd.DataFrame(audit).rename(columns={"ts": "일시", "actor": "작성자", "action": "작업",
                                                          "detail": "내용"}),
                     use_container_width=True, hide_index=True)

# ---------- 7 제안서 ----------
with tabs[6]:
    if proj["status"] != "승인" or not proj["approved_snapshot"]:
        st.info("손익 검토가 승인된 건에 대해서만 제안서를 생성할 수 있습니다.")
    else:
        snap = json.loads(proj["approved_snapshot"])
        st.write("외부 제출용 제안서에는 공급원가·운영비·손익·회수기간 등 내부 정보가 포함되지 않습니다.")
        key = f"opinion_{pid}"
        if st.button("검토 의견 문안 생성 (AI)"):
            with st.spinner("작성 중..."):
                text, src = draft_opinion(snap["project"], list(investment_by_category(snap["items"])))
            st.session_state[key] = text
            st.session_state[key + "_src"] = src
        if st.session_state.get(key + "_src") == "template":
            st.caption("ANTHROPIC_API_KEY가 없거나 호출에 실패해 기본 문안을 사용했습니다.")
        elif st.session_state.get(key + "_src") == "claude":
            st.caption("고객사명 가명 처리 및 금액 정보 제외 후 Claude로 작성한 초안입니다. 반드시 검토하세요.")
        opinion = st.text_area("검토 의견 및 추가 협의사항 (수정 가능)", st.session_state.get(key, ""), height=150)
        c1, c2 = st.columns(2)
        c1.download_button("📄 공급 제안서 (외부용) 다운로드",
                           build_external_proposal(snap, opinion),
                           file_name=f"공급제안서_{safe_name(snap['project']['customer'])}.docx",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        c2.download_button("🔒 내부 손익 검토서 (대외비) 다운로드",
                           build_internal_review(snap, snap.get("issues", []), db.get_audit(pid)),
                           file_name=f"내부손익검토서_{safe_name(snap['project']['customer'])}.docx",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
