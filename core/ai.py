"""Claude API 연동: 제안서 '검토 의견 및 추가 협의사항' 문안 초안 작성.

보안 원칙 (기획서 5.2):
- 고객사명은 가명으로 치환하고 민감정보 패턴을 마스킹한 뒤에만 전송한다.
- 원가·운영비·손익·투자비 금액은 프롬프트에 포함하지 않는다. 금액 계산은 core.calc가 담당한다.
- ANTHROPIC_API_KEY가 없거나 호출이 실패하면 고정 템플릿 문안으로 대체한다.
"""
from __future__ import annotations

import os

from .masking import mask_text

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

FALLBACK = (
    "- 본 제안은 현장 실사 및 설계 확정 결과에 따라 일부 조정될 수 있습니다.\n"
    "- 저장설비 설치 위치 및 배관 경로는 관련 법령에 따른 안전거리 검토 후 확정합니다.\n"
    "- 공급단가 및 계약 조건은 최종 협의 후 계약서에 반영합니다."
)


def draft_opinion(project: dict, categories: list[str]) -> tuple[str, str]:
    """(문안, 출처) 반환. 출처는 'claude' 또는 'template'."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return FALLBACK, "template"
    alias = {project["customer"]: "고객사"}
    context = mask_text(
        f"가스 종류: {project.get('gas') or '미정'}\n"
        f"공급 기간: {project.get('contract_years')}년\n"
        f"설치 공사 구분: {', '.join(categories) or '미정'}\n"
        f"현장 메모: {project.get('site_note') or '없음'}",
        alias,
    )
    prompt = (
        "산업가스 신규 공급 제안서의 '검토 의견 및 추가 협의사항' 항목을 한국어로 3~5개 불릿으로 작성하세요.\n"
        "금액·단가·수익성 수치는 언급하지 말고, 현장 확정·안전 법령 검토·계약 협의 등 일반적인 협의사항 위주로 쓰세요.\n\n"
        f"[사업 정보]\n{context}"
    )
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=MODEL, max_tokens=600, messages=[{"role": "user", "content": prompt}]
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        return (text or FALLBACK), ("claude" if text else "template")
    except Exception:
        return FALLBACK, "template"
