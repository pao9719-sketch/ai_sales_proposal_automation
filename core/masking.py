"""민감정보 비식별화. 외부 AI 전송 전에 반드시 통과시킨다 (F-10)."""
import re

_PATTERNS = [
    (re.compile(r"\b\d{6}-?[1-4]\d{6}\b"), "[주민번호]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{5}\b"), "[사업자번호]"),
    (re.compile(r"\b0\d{1,2}-\d{3,4}-\d{4}\b"), "[전화번호]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[이메일]"),
]


def mask_text(text: str, names: dict[str, str] | None = None) -> str:
    """names: {실명: 가명} 치환 사전 (고객사명 등)."""
    out = text or ""
    for real, alias in (names or {}).items():
        if real:
            out = out.replace(real, alias)
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out
