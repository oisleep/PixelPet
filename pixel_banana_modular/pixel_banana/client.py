from __future__ import annotations
from typing import Optional, List
import requests
from .textclean import strip_thinking, SOFT_STOPS


class LocalModelClient:
    def __init__(self, base_url: str, model_name: str):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = 30

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return r.ok
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if r.ok:
                data = r.json()
                models = data.get("models") or data.get("data") or []
                return [
                    m.get("name") or m.get("model")
                    for m in models
                    if (m.get("name") or m.get("model"))
                ]
        except Exception:
            pass
        return []

    def _post_chat(self, messages, options, keep_alive_sec: int = 0) -> str:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": options,
            "keep_alive": keep_alive_sec,
        }
        r = requests.post(
            f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
        )
        if not r.ok:
            return f"[HTTP {r.status_code}] {r.text[:160]}"
        data = r.json()
        msg = (data.get("message") or {}).get("content", "")
        err = data.get("error")
        if err and not msg:
            return f"[本地模型错误] {err}"
        return msg or ""

    def ask(
        self, prompt: str, system: Optional[str] = None, no_think: bool = True
    ) -> str:
        sys_prompt = system or ""
        if no_think:
            sys_prompt = (
                (sys_prompt + " ") if sys_prompt else ""
            ) + "不要输出思考、推理、过程或<think>标签；直接给答案，可分 1–3 句。"
        msgs = []
        if sys_prompt:
            msgs.append({"role": "system", "content": sys_prompt})
        msgs.append({"role": "user", "content": prompt})

        msg1 = self._post_chat(
            msgs, {"num_predict": 256, "temperature": 0.6}, keep_alive_sec=0
        )
        clean1 = strip_thinking(msg1)
        if clean1:
            return clean1

        msgs2 = list(msgs)
        if no_think:
            msgs2[0] = {
                "role": "system",
                "content": sys_prompt + " 严禁输出思考或任何标签，仅一句话答案。",
            }
        msg2 = self._post_chat(
            msgs2,
            {"num_predict": 256, "temperature": 0.6, "stop": SOFT_STOPS},
            keep_alive_sec=0,
        )
        clean2 = strip_thinking(msg2)
        if clean2:
            return clean2

        return self._fallback(prompt)

    def unload(self) -> bool:
        """请求卸载当前模型（释放显存/内存，不会停止服务）"""
        try:
            payload = {
                "model": self.model_name,
                "prompt": "",
                "stream": False,
                "keep_alive": 0,
            }
            r = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=5)
            return r.ok
        except Exception:
            return False

    @staticmethod
    def _fallback(prompt: str) -> str:
        p = prompt.strip()
        if any(k in p for k in ("你好", "hello", "hi")):
            return "你好，我是像素香蕉。今天也要补充维生素C！"
        if "天气" in p:
            return "关于天气：我可以试着查一下，但现在先给你一缕想象中的阳光☀️"
        if len(p) < 10:
            return "收到~"
        return "我在这儿，慢慢说。"
