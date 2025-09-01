# textclean.py

import re


MAX_OUTPUT_CHARS = 1200

SOFT_STOPS = [
    "系统：", "用户：", "System:", "User:", "analysis:", "Analysis:",
    "<think>", "</think>", "<analysis>", "</analysis>",
    "<assistant_thought>", "</assistant_thought>",
    "<scratchpad>", "</scratchpad>",
    "<|assistant_thought|>", "```think", "```analysis", "思考：", "分析：", "推理：",
]

# 支持 <think ...> 任意属性、各种别名标签与大小写
_THINK_TAGS = re.compile(
    r"(?is)<\s*(?:think|thinking|thought|analysis|reasoning|scratchpad|assistant_thought)\b[^>]*>"
    r".*?"
    r"</\s*(?:think|thinking|thought|analysis|reasoning|scratchpad|assistant_thought)\s*>"
)

# 清理 ```think / ```analysis 等代码块
_TRIPLE_BACKTICK_THINK = re.compile(r"(?is)```(?:think|thinking|thought|analysis|reasoning)[\s\S]*?```")

# 行首“思考/推理/分析：……块”
_THINK_BLOCK = re.compile(r"(?is)^\s*(?:思考|推理|分析)\s*[:：].*?(?:\n\s*\n|$)")

_FINAL_MARK = re.compile(r"(?is)(?:最终答案|答案|结论|Final Answer|Answer)\s*[:：]")

def strip_thinking(txt: str) -> str:
    if not txt:
        return ""
    txt = _THINK_TAGS.sub("", txt)
    txt = _TRIPLE_BACKTICK_THINK.sub("", txt)
    txt = _THINK_BLOCK.sub("", txt)
    # 去掉孤立起止标签
    txt = re.sub(r"(?is)</?\s*(?:think|analysis|assistant_thought|scratchpad)\s*>", "", txt)
    # 若仍出现未闭合的开标签，直接截断到标签前
    m = re.search(r"(?is)<\s*(?:think|assistant_thought|analysis)[^>]*>", txt)
    if m:
        txt = txt[:m.start()]
    m2 = _FINAL_MARK.search(txt)
    if m2:
        txt = txt[m2.end():]
    txt = re.sub(r"^(?:答|助手|Assistant)\s*[:：]\s*", "", txt.strip())
    lines = [line.rstrip() for line in txt.splitlines() if line.strip()]
    out = "\n".join(lines)
    return out if MAX_OUTPUT_CHARS == 0 else out[:MAX_OUTPUT_CHARS]
