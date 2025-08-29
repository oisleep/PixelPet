
from __future__ import annotations
import re

SOFT_STOPS = ["系统：", "用户：", "System:", "User:", "analysis:", "Analysis:"]

_THINK_TAG = re.compile(r"(?is)<think>.*?</think>")
_THINK_BLOCK = re.compile(r"(?is)^\s*(?:思考|推理|分析)\s*[:：].*?(?:\n\s*\n|$)")
_FINAL_MARK = re.compile(r"(?is)(?:最终答案|答案|结论|Final Answer|Answer)\s*[:：]")

def strip_thinking(txt: str) -> str:
    if not txt:
        return ""
    txt = _THINK_TAG.sub("", txt)
    txt = _THINK_BLOCK.sub("", txt)
    m = _FINAL_MARK.search(txt)
    if m:
        txt = txt[m.end():]
    txt = re.sub(r"^(?:答|助手|Assistant)\s*[:：]\s*", "", txt.strip())
    lines = [line.rstrip() for line in txt.splitlines() if line.strip()]
    return "\n".join(lines)[:400]
