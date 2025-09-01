
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json

APP_ID = "pixel_banana_pet"
CONF_DIR = Path.home() / f".{APP_ID}"
CONF_PATH = CONF_DIR / "config.json"

DEFAULT_CFG = {
    "model_url": "http://127.0.0.1:11434",
    "model_name": "qwen3:1.7b",
    "city": "",
    "auto_bubble": True,
    "opacity": 0.98,
    "unload_on_exit": True,
    "user_name": "Barbara",   # ← 新增默认称呼
}

@dataclass
class Settings:
    model_url: str = DEFAULT_CFG["model_url"]
    model_name: str = DEFAULT_CFG["model_name"]
    city: str = DEFAULT_CFG["city"]
    auto_bubble: bool = DEFAULT_CFG["auto_bubble"]
    opacity: float = DEFAULT_CFG["opacity"]
    unload_on_exit: bool = DEFAULT_CFG["unload_on_exit"]
    user_name: str = DEFAULT_CFG["user_name"]  # ← 新增字段

    @classmethod
    def load(cls) -> "Settings":
        try:
            CONF_DIR.mkdir(parents=True, exist_ok=True)
            data = DEFAULT_CFG.copy()
            if CONF_PATH.exists():
                data.update(json.loads(CONF_PATH.read_text(encoding="utf-8")))
            else:
                CONF_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return cls(**data)
        except Exception:
            return cls()

    def save(self) -> None:
        data = {
            "model_url": self.model_url,
            "model_name": self.model_name,
            "city": self.city,
            "auto_bubble": self.auto_bubble,
            "opacity": self.opacity,
            "unload_on_exit": self.unload_on_exit,
            "user_name": self.user_name,  # ← 保存
        }
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        CONF_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
