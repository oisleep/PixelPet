#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pixel Banana：极简像素香蕉桌面宠物（Mac / Windows）

本版改动（Windows 专项“保险丝” + 非切换式点击行为）：
- 单击香蕉：始终“召唤输入条”（不再切换隐藏）；若已显示则聚焦并置顶
- Windows：禁用阴影 + 边界钳制 + 4px 硬裁剪，避免 UpdateLayeredWindowIndirect 报错
- 其他同上一版 PixelPet_fixed.py
"""

from __future__ import annotations
import json, random, threading, time, difflib, re, sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import requests
from PySide6 import QtCore, QtGui, QtWidgets

from PySide6.QtCore import Qt, QRect, QRectF, QSize, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPainterPath, QPen, QFontMetrics, QGuiApplication
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsDropShadowEffect

APP_ID = "pixel_banana_pet"
CONF_DIR = Path.home() / f".{APP_ID}"
CONF_PATH = CONF_DIR / "config.json"

DEFAULT_CFG = {
    "model_url": "http://127.0.0.1:11434",
    "model_name": "qwen3:1.7b",
    "city": "",
    "auto_bubble": True,
    "opacity": 0.98,
}

SOFT_STOPS = ["系统：", "用户：", "System:", "User:", "analysis:", "Analysis:"]

class PrettyBubble(QWidget):
    BG_COLOR = QColor("#FFF3B0")
    FG_COLOR = QColor("#5C4905")
    BORDER_COLOR = QColor(0, 0, 0, 30)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setMouseTracking(True)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        f = self._label.font(); f.setPointSizeF(11.5); self._label.setFont(f)

        lay = QVBoxLayout(self); lay.setContentsMargins(14, 12, 14, 12); lay.addWidget(self._label)

        if sys.platform.startswith("win"):
            self.setGraphicsEffect(None)
        else:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(24); shadow.setOffset(0, 6); shadow.setColor(QColor(0, 0, 0, 80))
            self.setGraphicsEffect(shadow)

        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(220); self._fade.setStartValue(0.0); self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        self._pop = QPropertyAnimation(self, b"geometry", self)
        self._pop.setDuration(220); self._pop.setEasingCurve(QEasingCurve.OutBack)

        self._tail_size = 10; self._radius = 14; self._tail_side = "bottom"
        self._max_width = 360

        self._auto_close_ms = 5000
        self._close_timer = QTimer(self); self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.fade_out)

        self._typing = False; self._full_text = ""; self._type_idx = 0
        self._type_timer = QTimer(self); self._type_timer.setInterval(16)
        self._type_timer.timeout.connect(self._type_step)

        pal = self._label.palette()
        pal.setColor(self._label.foregroundRole(), self.FG_COLOR)
        self._label.setPalette(pal)

    def set_typing(self, enabled: bool): self._typing = bool(enabled)
    def set_max_width(self, w: int): self._max_width = max(220, int(w))
    def set_auto_close_ms(self, ms: int): self._auto_close_ms = max(0, int(ms))

    def popup(self, text: str, anchor_rect: QRect, prefer="right"):
        self._prepare_text(text)
        hint = self._size_hint_for(self._label.text() if not self._typing else "")
        geo = self._suggest_geometry(anchor_rect, hint, prefer)

        start = QRect(geo); start.setWidth(int(geo.width()*0.9)); start.setHeight(int(geo.height()*0.9))
        start.moveCenter(geo.center())

        self.setGeometry(start); self.setWindowOpacity(0.0); self.show()
        self._fade.stop(); self._fade.setStartValue(0.0); self._fade.setEndValue(1.0); self._fade.start()
        self._pop.stop(); self._pop.setStartValue(start); self._pop.setEndValue(geo); self._pop.start()
        if self._auto_close_ms > 0: self._close_timer.start(self._auto_close_ms)

    def fade_out(self):
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(180); anim.setStartValue(self.windowOpacity()); anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic); anim.finished.connect(self.hide); anim.start()

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect(); body = QRectF(rect)
        if self._tail_side == "bottom": body.adjust(0, 0, 0, -self._tail_size)
        elif self._tail_side == "top": body.adjust(0, self._tail_size, 0, 0)
        elif self._tail_side == "right": body.adjust(0, 0, -self._tail_size, 0)
        elif self._tail_side == "left": body.adjust(self._tail_size, 0, 0, 0)

        path = QPainterPath(); path.addRoundedRect(body, self._radius, self._radius)
        tail = QPainterPath(); ts = float(self._tail_size); tw = ts*2.0
        if self._tail_side in ("bottom","top"):
            cx = body.center().x()
            if self._tail_side=="bottom":
                tail.moveTo(cx - tw/2, body.bottom()); tail.lineTo(cx + tw/2, body.bottom()); tail.lineTo(cx, body.bottom()+ts)
            else:
                tail.moveTo(cx - tw/2, body.top()); tail.lineTo(cx + tw/2, body.top()); tail.lineTo(cx, body.top()-ts)
        else:
            cy = body.center().y()
            if self._tail_side=="right":
                tail.moveTo(body.right(), cy - tw/2); tail.lineTo(body.right(), cy + tw/2); tail.lineTo(body.right()+ts, cy)
            else:
                tail.moveTo(body.left(), cy - tw/2); tail.lineTo(body.left(), cy + tw/2); tail.lineTo(body.left()-ts, cy)
        tail.closeSubpath(); path.addPath(tail)

        p.setPen(QPen(self.BORDER_COLOR, 1)); p.setBrush(self.BG_COLOR); p.drawPath(path)

    def _prepare_text(self, text: str):
        text = (text or "").strip()
        if self._typing:
            self._full_text = text; self._type_idx = 0; self._label.setText(""); self._type_timer.start()
        else:
            self._label.setText(text); self._type_timer.stop()
        self._label.setFixedWidth(self._max_width); self.adjustSize()

    def _type_step(self):
        if self._type_idx >= len(self._full_text): self._type_timer.stop(); return
        step = max(1, len(self._full_text)//140); self._type_idx += step
        self._label.setText(self._full_text[:self._type_idx]); self.adjustSize()

    def _size_hint_for(self, text: str) -> QSize:
        if text == "": text = " " * 4
        fm = QFontMetrics(self._label.font())
        br = fm.boundingRect(0, 0, self._max_width, 10_000, Qt.TextWordWrap, text)
        w = min(self._max_width, max(160, br.width())) + 28
        h = br.height() + 24 + self._tail_size
        return QSize(w, h)

    def sizeHint(self) -> QSize: return self._size_hint_for(self._label.text())

    def _suggest_geometry(self, anchor_rect: QRect, hint_size: QSize, prefer: str) -> QRect:
        screen = (QGuiApplication.screenAt(anchor_rect.center())
                  or (self.windowHandle().screen() if self.windowHandle() else None)
                  or QGuiApplication.primaryScreen())
        geo = screen.availableGeometry()

        w, h = hint_size.width(), hint_size.height()
        candidates = {
            "right": QRect(anchor_rect.right()+12, anchor_rect.center().y()-h//2, w, h),
            "left":  QRect(anchor_rect.left()-w-12, anchor_rect.center().y()-h//2, w, h),
            "above": QRect(anchor_rect.center().x()-w//2, anchor_rect.top()-h-12, w, h),
            "below": QRect(anchor_rect.center().x()-w//2, anchor_rect.bottom()+12, w, h),
        }
        order = [prefer] + [k for k in ("right","left","above","below") if k!=prefer]
        pad = 12
        for k in order:
            r = candidates[k]
            x = max(geo.left()+pad, min(r.x(), geo.right()-w-pad))
            y = max(geo.top()+pad,  min(r.y(), geo.bottom()-h-pad))
            r = QRect(x, y, w, h).intersected(geo.adjusted(4,4,-4,-4))
            if r.width() > 16 and r.height() > 16:
                self._tail_side = {"right":"left","left":"right","above":"bottom","below":"top"}[k]
                return r

        self._tail_side = "bottom"
        r = QRect(geo.center().x()-w//2, geo.center().y()-h//2, w, h)
        return r.intersected(geo.adjusted(4,4,-4,-4))

# --------------------------- 配置 ---------------------------
@dataclass
class Settings:
    model_url: str = DEFAULT_CFG["model_url"]
    model_name: str = DEFAULT_CFG["model_name"]
    city: str = DEFAULT_CFG["city"]
    auto_bubble: bool = DEFAULT_CFG["auto_bubble"]
    opacity: float = DEFAULT_CFG["opacity"]

    @classmethod
    def load(cls) -> "Settings":
        try:
            CONF_DIR.mkdir(parents=True, exist_ok=True)
            data = DEFAULT_CFG.copy()
            if CONF_PATH.exists(): data.update(json.loads(CONF_PATH.read_text(encoding="utf-8")))
            else: CONF_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return cls(**data)
        except Exception:
            return cls()

    def save(self) -> None:
        data = {"model_url": self.model_url, "model_name": self.model_name, "city": self.city,
                "auto_bubble": self.auto_bubble, "opacity": self.opacity}
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        CONF_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# --------------------------- 文本清洗 ---------------------------
_THINK_TAG = re.compile(r"(?is)<think>.*?</think>")
_THINK_BLOCK = re.compile(r"(?is)^\s*(?:思考|推理|分析)\s*[:：].*?(?:\n\s*\n|$)")
_FINAL_MARK = re.compile(r"(?is)(?:最终答案|答案|结论|Final Answer|Answer)\s*[:：]")

def strip_thinking(txt: str) -> str:
    if not txt: return ""
    txt = _THINK_TAG.sub("", txt)
    txt = _THINK_BLOCK.sub("", txt)
    m = _FINAL_MARK.search(txt)
    if m: txt = txt[m.end():]
    txt = re.sub(r"^(?:答|助手|Assistant)\s*[:：]\s*", "", txt.strip())
    lines = [line.rstrip() for line in txt.splitlines() if line.strip()]
    return "\n".join(lines)[:400]

# --------------------------- Ollama 客户端 ---------------------------
class LocalModelClient:
    def __init__(self, base_url: str, model_name: str):
        self.base_url = base_url.rstrip("/"); self.model_name = model_name; self.timeout = 30

    def is_available(self) -> bool:
        try: r = requests.get(f"{self.base_url}/api/tags", timeout=3); return r.ok
        except Exception: return False

    def list_models(self) -> List[str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if r.ok:
                data = r.json(); models = data.get("models") or data.get("data") or []
                return [m.get("name") or m.get("model") for m in models if (m.get("name") or m.get("model"))]
        except Exception: pass
        return []

    def _post_chat(self, messages, options) -> str:
        r = requests.post(f"{self.base_url}/api/chat",
                          json={"model": self.model_name, "messages": messages, "stream": False, "options": options},
                          timeout=self.timeout)
        if not r.ok: return f"[HTTP {r.status_code}] {r.text[:160]}"
        data = r.json(); msg = (data.get("message") or {}).get("content", ""); err = data.get("error")
        if err and not msg: return f"[本地模型错误] {err}"
        return msg or ""

    def ask(self, prompt: str, system: Optional[str] = None, no_think: bool = True) -> str:
        sys_prompt = system or ""
        if no_think:
            sys_prompt = ((sys_prompt + " ") if sys_prompt else "") + "不要输出思考、推理、过程或<think>标签；直接给答案，可分 1–3 句。"
        msgs = []
        if sys_prompt: msgs.append({"role":"system","content":sys_prompt})
        msgs.append({"role":"user","content":prompt})

        msg1 = self._post_chat(msgs, {"num_predict": 256, "temperature": 0.6})
        clean1 = strip_thinking(msg1)
        if clean1: return clean1

        msgs2 = list(msgs)
        if no_think: msgs2[0] = {"role":"system","content":sys_prompt + " 严禁输出思考或任何标签，仅一句话答案。"}
        msg2 = self._post_chat(msgs2, {"num_predict": 256, "temperature": 0.6, "stop": SOFT_STOPS})
        clean2 = strip_thinking(msg2)
        if clean2: return clean2

        return self._fallback(prompt)

    @staticmethod
    def _fallback(prompt: str) -> str:
        p = prompt.strip()
        if any(k in p for k in ("你好","hello","hi")): return "你好，我是像素香蕉。今天也要补充维生素C！"
        if "天气" in p: return "关于天气：我可以试着查一下，但现在先给你一缕想象中的阳光☀️"
        if len(p) < 10: return "收到~"
        return "我在这儿，慢慢说。"

# --------------------------- 天气 ---------------------------
class Weather:
    @staticmethod
    def by_city(city: str) -> Optional[str]:
        city = (city or "").strip()
        if not city: return None
        try:
            g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": city, "count": 1, "language": "zh", "format": "json"}, timeout=5)
            g.raise_for_status()
            items = g.json().get("results") or []
            if not items: return None
            lat, lon = items[0]["latitude"], items[0]["longitude"]
            w = requests.get("https://api.open-meteo.com/v1/forecast",
                             params={"latitude": lat, "longitude": lon, "current_weather": True,
                                     "hourly": "temperature_2m", "timezone": "auto", "forecast_days": 1},
                             timeout=5)
            w.raise_for_status()
            data = w.json().get("current_weather", {})
            temp, ws, code = data.get("temperature"), data.get("windspeed"), data.get("weathercode")
            mapping = {0:"晴",1:"多云",2:"多云",3:"阴",45:"雾",48:"雾",51:"小雨",61:"小雨",63:"中雨",65:"大雨",71:"小雪",73:"中雪",75:"大雪",95:"雷阵雨"}
            desc = mapping.get(int(code or 0), "天气不明")
            if temp is not None: return f"{city} 天气：{desc}，{temp:.0f}°C，风速{ws:.0f} km/h"
        except Exception:
            return None
        return None

# --------------------------- 旧气泡（保留但不再使用） ---------------------------
class Bubble(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget, text: str, ms: int = 2800):
        super().__init__(parent)
        self.text = text
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool)
        self._opacity = 0.0
        self.anim = QtCore.QPropertyAnimation(self, b"opacity", self)
        self.anim.setDuration(220); self.anim.setStartValue(0.0); self.anim.setEndValue(1.0)
        self.hide_timer = QtCore.QTimer(self); self.hide_timer.setInterval(ms); self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)
        self._pad, self._arrow = 10, 8
        self.fm = QtGui.QFontMetrics(self.font())
        self.resize_to_text()

    def resize_to_text(self):
        max_w, lines, cur = 240, [], ""
        for ch in self.text:
            if self.fm.horizontalAdvance(cur + ch) > max_w - 2 * self._pad:
                lines.append(cur); cur = ch
            else:
                cur += ch
        if cur: lines.append(cur)
        self.lines = lines
        w = min(max_w, max(self.fm.horizontalAdvance(line) for line in lines) + 2 * self._pad)
        h = len(lines) * (self.fm.height() + 2) + 2 * self._pad + self._arrow
        self.resize(w, h)

    def setText(self, text: str): self.text = text; self.resize_to_text(); self.update()

    def paintEvent(self, e: QtGui.QPaintEvent):  # noqa
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        body = QtCore.QRect(rect.left(), rect.top(), rect.width(), rect.height() - self._arrow)
        path = QtGui.QPainterPath(); path.addRoundedRect(body, 10, 10)
        tri = QtGui.QPolygon([
            QtCore.QPoint(body.left() + body.width()//3, body.bottom()),
            QtCore.QPoint(body.left() + body.width()//3 + 12, body.bottom()),
            QtCore.QPoint(body.left() + body.width()//3 + 6, body.bottom() + self._arrow),
        ])
        p.setOpacity(self._opacity); p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(30, 30, 30, 230))
        p.drawPath(path); p.drawPolygon(tri)
        p.setPen(QtGui.QColor(240, 240, 240))
        x = body.left() + self._pad; y = body.top() + self._pad + self.fm.ascent()
        for line in self.lines: p.drawText(x, y, line); y += self.fm.height() + 2

    def get_opacity(self): return self._opacity
    def set_opacity(self, v: float): self._opacity = float(v); self.update()
    opacity = QtCore.Property(float, get_opacity, set_opacity)

    def popup(self, pos: QtCore.QPoint):
        self.move(pos); self.show(); self.raise_()
        self.anim.stop(); self.anim.setDirection(QtCore.QAbstractAnimation.Forward); self.anim.start()
        self.hide_timer.start()

    def fade_out(self):
        self.anim.stop(); self.anim.setDirection(QtCore.QAbstractAnimation.Backward)
        self.anim.finished.connect(self.hide); self.anim.start()

# --------------------------- 像素香蕉（固定外观） ---------------------------
class BananaSprite(QtWidgets.QWidget):
    clicked = QtCore.Signal()
    def __init__(self, scale: int = 6, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.scale = max(3, scale)
        self.maturity = 1  # 固定为“正好”，不随点击改变
        self.grid = self._make_grid()
        self.setFixedSize(self.grid.width * self.scale, self.grid.height * self.scale)

    class Grid:
        def __init__(self, w, h, points): self.width, self.height, self.points = w, h, points

    def _make_grid(self) -> "BananaSprite.Grid":
        w, h = 22, 16; pts = set()
        body = [
            "......................","......1111111.........","....11111111111....3..","...1111111111111..3...",
            "..111111111111111.....","..1111111111111111....","..1111111111111111....","...111111111111111....",
            "....11111111111111....",".....111111111111.....","......1111111111..2...","........1111111..22...",
            "..........111.....2...","............1.........","......................","......................",
        ]
        shadow = [(x,y) for y,row in enumerate(body) for x,ch in enumerate(row) if ch=="1" and (y>=9 or x>=12)]
        for y,row in enumerate(body):
            for x,ch in enumerate(row):
                if ch=="1": pts.add((x,y,1))
        for (x,y) in shadow: pts.add((x, y+1 if y+1<h else y, 2))
        pts.add((18,2,3)); pts.add((19,2,3))
        for x,y in ((7,4),(8,5),(6,6)): pts.add((x,y,4))
        return BananaSprite.Grid(w,h,sorted(list(pts)))

    def set_maturity(self, m: int):  # 保留以防未来需要，但不在应用中调用
        self.maturity = max(0, min(2, m)); self.update()

    def paintEvent(self, e: QtGui.QPaintEvent):  # noqa
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        c_body, c_shadow = QtGui.QColor(250,208,60), QtGui.QColor(210,170,50)
        c_stalk, c_high = QtGui.QColor(90,60,40), QtGui.QColor(255,255,240)
        for (x,y,val) in self.grid.points:
            color = c_body if val==1 else c_shadow if val==2 else c_stalk if val==3 else c_high if val==4 else QtGui.QColor(0,0,0,0)
            p.fillRect(x*self.scale, y*self.scale, self.scale, self.scale, color)

    def mousePressEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button()==QtCore.Qt.LeftButton:
            self._press_pos = e.globalPosition().toPoint(); self._press_local = e.position().toPoint(); self._press_ms = time.time(); e.accept()
        elif e.button()==QtCore.Qt.RightButton:
            self.parent().customContextMenuRequested.emit(e.globalPosition().toPoint()); e.accept()
        else: e.ignore()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.buttons() & QtCore.Qt.LeftButton:
            gp = e.globalPosition().toPoint(); diff = gp - self._press_pos
            if diff.manhattanLength() >= 3: self.parent().move(self.parent().pos()+diff); self._press_pos = gp

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button()==QtCore.Qt.LeftButton:
            moved = (e.position().toPoint() - self._press_local).manhattanLength() > 3
            dt = (time.time() - getattr(self, "_press_ms", time.time()))
            if not moved and dt < 0.3: self.clicked.emit()

# --------------------------- 自检对话框 ---------------------------
class SelfCheckDialog(QtWidgets.QDialog):
    def __init__(self, settings: Settings, client: LocalModelClient, parent=None):
        super().__init__(parent)
        self.settings, self.client = settings, client
        self.setWindowTitle("像素香蕉 · 连接自检")
        self.resize(560, 440)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.view = QtWidgets.QTextEdit(self); self.view.setReadOnly(True)
        self.btn_run = QtWidgets.QPushButton("重新测试")
        self.btn_close = QtWidgets.QPushButton("关闭")
        self.btn_run.clicked.connect(self.start); self.btn_close.clicked.connect(self.accept)

        lay = QtWidgets.QVBoxLayout(self); lay.addWidget(self.view)
        hl = QtWidgets.QHBoxLayout(); hl.addStretch(1); hl.addWidget(self.btn_run); hl.addWidget(self.btn_close); lay.addLayout(hl)
        self.start()

    def log(self, s: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.view.append(f"[{ts}] {s}"); self.view.moveCursor(QtGui.QTextCursor.End)

    def start(self):
        self.view.clear(); self.log("开始自检…"); self.btn_run.setEnabled(False)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        url = self.settings.model_url.rstrip("/"); name = self.settings.model_name
        try:
            t0 = time.perf_counter(); r = requests.get(f"{url}/api/tags", timeout=5); dt = (time.perf_counter()-t0)*1000
            if not r.ok: self._done(f"无法连接 Ollama（HTTP {r.status_code}）：{r.text[:200]}"); return
            self.log(f"✔ /api/tags 可达，{dt:.0f} ms")
            models = r.json().get("models") or r.json().get("data") or []
            names = [m.get("name") or m.get("model") for m in models if (m.get("name") or m.get("model"))]
            if name in names: self.log(f"✔ 已安装模型：{name}")
            else:
                self.log(f"✖ 未找到模型：{name}")
                if names:
                    cand = difflib.get_close_matches(name, names, n=3, cutoff=0.3)
                    if cand: self.log("  可能想要的是：" + ", ".join(cand))
                self._done("请 `ollama pull` 对应模型，或在菜单里修改模型名。"); return
        except Exception as ex:
            self._done(f"✖ 无法访问 Ollama：{ex}"); return

        try:
            t1 = time.perf_counter()
            payload = {"model": name, "messages": [{"role":"user","content":"只回：香蕉OK"}], "stream": False}
            r = requests.post(f"{url}/api/chat", json=payload, timeout=12)
            dt = (time.perf_counter()-t1)*1000
            if not r.ok: self._done(f"✖ /api/chat 失败（HTTP {r.status_code}）：{r.text[:200]}"); return
            raw = (r.json().get("message") or {}).get("content", "")
            clean = strip_thinking(raw) or raw[:24]
            self.log(f"✔ /api/chat 正常，用时 {dt:.0f} ms；回声：{clean!r}")
        except Exception as ex:
            self._done(f"✖ /api/chat 调用异常：{ex}"); return

        self._done("自检完成：一切正常 ✅")

    def _done(self, tail: str):
        self.log(tail); self.btn_run.setEnabled(True)

# --------------------------- 底部半透明输入条（稳定版） ---------------------------
class InputBar(QtWidgets.QWidget):
    sigSubmit = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, False)
        self.setWindowTitle("像素香蕉 · 输入")

        self.back = QtWidgets.QFrame(self)
        self.back.setStyleSheet("""
            QFrame { background: rgba(25,25,25,190); border-radius: 12px; }
            QLineEdit { border: none; padding: 10px 12px; color: #f2f2f2; background: transparent; font-size: 14px; }
            QPushButton { background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.18);
                          border-radius:10px; padding:8px 12px; color:#f2f2f2; }
            QPushButton:hover { background: rgba(255,255,255,0.18); }
        """)
        lay = QtWidgets.QHBoxLayout(self.back); lay.setContentsMargins(10,8,10,8); lay.setSpacing(8)
        self.edit = QtWidgets.QLineEdit(self.back); self.edit.setPlaceholderText("和香蕉聊点什么…（Enter 发送，Esc 关闭）")
        self.btn = QtWidgets.QPushButton("发送", self.back)
        lay.addWidget(self.edit, 1); lay.addWidget(self.btn, 0)

        root = QtWidgets.QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.addWidget(self.back)

        self.btn.clicked.connect(self._submit)
        self.edit.returnPressed.connect(self._submit)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160); self.setWindowOpacity(0.0)

        if sys.platform.startswith("win"):
            self.setGraphicsEffect(None)

    def keyPressEvent(self, e: QtGui.QKeyEvent):
        if e.key() == Qt.Key_Escape:
            self.hide_with_fade(); e.accept(); return
        super().keyPressEvent(e)

    def show_at_bottom(self):
        # 如果已经可见，只做聚焦与置顶，不要再触发隐藏/切换
        if self.isVisible():
            try:
                self.raise_()
                self.activateWindow()
            except Exception:
                pass
            self.edit.setFocus(); self.edit.selectAll()
            return

        scr_obj = (QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
                   or (self.parent().windowHandle().screen() if self.parent() and self.parent().windowHandle() else None)
                   or QtGui.QGuiApplication.primaryScreen())
        geo = scr_obj.availableGeometry()

        w, h = 520, 48
        x = geo.center().x() - w // 2
        y = geo.bottom() - h - 24

        pad = 12
        x = max(geo.left() + pad, min(x, geo.right() - w - pad))
        y = max(geo.top()  + pad, min(y, geo.bottom() - h - pad))

        rect = QRect(int(x), int(y), int(w), int(h))
        rect = rect.intersected(geo.adjusted(4,4,-4,-4))

        self.setGeometry(rect)
        self.back.setGeometry(0, 0, rect.width(), rect.height())

        self.setWindowOpacity(0.0); self.show(); self.raise_()
        self._fade.stop(); self._fade.setStartValue(0.0); self._fade.setEndValue(1.0); self._fade.start()
        self.edit.setFocus(); self.edit.selectAll()

    def hide_with_fade(self):
        self._fade.stop(); self._fade.setStartValue(self.windowOpacity()); self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide); self._fade.start()

    def _submit(self):
        text = self.edit.text().strip()
        if not text: return
        self.edit.clear()
        self.hide_with_fade()
        self.sigSubmit.emit(text)

# --------------------------- 主窗口（宠物） ---------------------------
class PetWindow(QtWidgets.QWidget):
    customContextMenuRequested = QtCore.Signal(QtCore.QPoint)
    sigSay = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.client = LocalModelClient(self.settings.model_url, self.settings.model_name)

        self.setWindowTitle("像素香蕉")
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
        self.setWindowFlag(QtCore.Qt.Tool, True)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

        self.sprite = BananaSprite(scale=6, parent=self)
        self.sprite.clicked.connect(self.on_click)
        self.resize(self.sprite.width(), self.sprite.height())

        self.tray = QtWidgets.QSystemTrayIcon(QtGui.QIcon.fromTheme("emblem-favorite"), self)
        self.tray.setToolTip("像素香蕉"); self.tray.setVisible(True)
        self.tray_menu = self._make_menu(); self.tray.setContextMenu(self.tray_menu)

        self.auto_timer = QtCore.QTimer(self); self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self.auto_bubble)
        if self.settings.auto_bubble: self._schedule_auto()

        self.sigSay.connect(self.say)
        QtCore.QTimer.singleShot(800, lambda: self.say("你好，我是像素香蕉，单击我可以在底部输入~"))
        self.setWindowOpacity(self.settings.opacity)

        self.input_bar = InputBar(None)
        self.input_bar.sigSubmit.connect(self._handle_user_submit)
        self._pretty = PrettyBubble(None)
        self._pretty.set_typing(True)
        self._pretty.set_max_width(360)

    def _make_menu(self) -> QtWidgets.QMenu:
        m = QtWidgets.QMenu()
        m.addAction("打开聊天窗…", self.open_chat)
        m.addAction("连接自检…", self.open_selfcheck)
        m.addSeparator()
        act_toggle = m.addAction("切换自动冒泡", self.toggle_auto)
        act_toggle.setCheckable(True); act_toggle.setChecked(self.settings.auto_bubble)
        sub = m.addMenu("透明度")
        for pct in (100, 95, 90, 85, 80):
            act = sub.addAction(f"{pct}%"); act.triggered.connect(lambda _=False, v=pct: self.set_opacity_pct(v))
        m.addSeparator()
        m.addAction("设置模型名…", self.change_model)
        m.addAction("设置城市（天气）…", self.change_city)
        m.addSeparator()
        m.addAction("退出", QtWidgets.QApplication.quit)
        return m

    def show_menu(self, global_pos: QtCore.QPoint): self._make_menu().exec(global_pos)
    def open_chat(self): ChatDialog(self.client, self).exec()
    def open_selfcheck(self): SelfCheckDialog(self.settings, self.client, self).exec()

    def toggle_auto(self):
        self.settings.auto_bubble = not self.settings.auto_bubble; self.settings.save()
        if self.settings.auto_bubble: self._schedule_auto()
        else: self.auto_timer.stop()

    def set_opacity_pct(self, pct: int):
        self.settings.opacity = max(0.3, min(1.0, pct/100.0))
        self.settings.save(); self.setWindowOpacity(self.settings.opacity)

    def change_model(self):
        cur = self.settings.model_name
        text, ok = QtWidgets.QInputDialog.getText(self, "设置模型名", "Ollama 模型名：", text=cur)
        if ok and text.strip():
            self.settings.model_name = text.strip(); self.settings.save()
            self.say(f"好的，之后用 {self.settings.model_name}。")

    def change_city(self):
        cur = self.settings.city
        text, ok = QtWidgets.QInputDialog.getText(self, "设置城市", "用于天气查询（示例：南京 / Beijing）：", text=cur)
        if ok:
            self.settings.city = text.strip(); self.settings.save()
            self.say(f"知道了，城市设为 {self.settings.city}。" if self.settings.city else "已清除城市设置。")

    @QtCore.Slot(str)
    def say(self, text: str):
        self._pretty.popup(text, anchor_rect=self.frameGeometry(), prefer="right")

    def on_click(self):
        # 改为“只召唤不关闭”：反复点击香蕉不会把输入条隐藏
        self.input_bar.show_at_bottom()

    def _schedule_auto(self):
        self.auto_timer.start(random.randint(30_000, 75_000))

    def auto_bubble(self):
        if not self.settings.auto_bubble: return
        choice = random.random()
        if choice < 0.3:
            self.say(f"今天是 {datetime.now().strftime('%Y-%m-%d, %H:%M')}")
        elif choice < 0.55:
            text = Weather.by_city(self.settings.city) if self.settings.city else None
            self.say(text or "天气如何？要不要我给你一点阳光能量☀️")
        elif choice < 0.8 and self.client.is_available():
            def _work():
                prompt = random.choice([
                    "用一句极简中文问候我，带点俏皮。",
                    "给我一句 10 字以内的小提醒（健康/效率/休息），中文。",
                    "用一句短句夸夸今天的自己，中文。",
                ])
                system = "你是像素香蕉，用中文简短回复（≤3句），不要输出<think>或过程标签。"
                reply = self.client.ask(prompt, system=system, no_think=True)
                self.sigSay.emit(reply)
            threading.Thread(target=_work, daemon=True).start()
        else:
            self.say(random.choice([
                "补水了吗？香蕉提醒你喝口水。",
                "休息 20 秒，放松下眼睛。",
                "保存一下文件，防止灵感蒸发。",
                "试试专注 25 分钟？",
            ]))
        self._schedule_auto()

    def _handle_user_submit(self, user_text: str):
        def _ask():
            system = ("你是像素香蕉。用中文回答，友好、简洁但不限字数（1–3句）。"
                      "不要输出<think>或任何过程标记。")
            reply = self.client.ask(user_text, system=system, no_think=True)
            self.sigSay.emit(reply)
        threading.Thread(target=_ask, daemon=True).start()

    def mousePressEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button()==QtCore.Qt.LeftButton:
            self._press_pos = e.globalPosition().toPoint(); e.accept()
        else: e.ignore()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.buttons() & QtCore.Qt.LeftButton and hasattr(self, "_press_pos"):
            gp = e.globalPosition().toPoint(); diff = gp - self._press_pos
            if diff.manhattanLength() >= 2: self.move(self.pos()+diff); self._press_pos = gp

# --------------------------- 简易聊天窗（可选，保留） ---------------------------
class ChatDialog(QtWidgets.QDialog):
    def __init__(self, client: LocalModelClient, parent=None):
        super().__init__(parent); self.client = client
        self.setWindowTitle("像素香蕉 · 对话"); self.resize(420, 420)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.view = QtWidgets.QTextEdit(self); self.view.setReadOnly(True)
        self.input = QtWidgets.QLineEdit(self)
        self.btn = QtWidgets.QPushButton("发送"); self.btn.clicked.connect(self.on_send)
        lay = QtWidgets.QVBoxLayout(self); lay.addWidget(self.view)
        hl = QtWidgets.QHBoxLayout(); hl.addWidget(self.input, 1); hl.addWidget(self.btn); lay.addLayout(hl)
        self.input.returnPressed.connect(self.on_send)
        self._append("系统", "聊点什么？")

    def _append(self, who: str, text: str):
        self.view.append(f"<b>{who}</b>：{QtGui.QGuiApplication.translate('', text)}")

    def on_send(self):
        text = self.input.text().strip()
        if not text: return
        self.input.clear(); self._append("你", text)
        self.btn.setEnabled(False); self.btn.setText("思考中…"); self.input.setEnabled(False)
        threading.Thread(target=self._ask_thread, args=(text,), daemon=True).start()

    def _ask_thread(self, text: str):
        system = ("你是像素香蕉。用中文回答，友好、简洁但不限字数（1–3句）。"
                  "不要输出<think>或任何过程标记。")
        reply = self.client.ask(text, system=system, no_think=True)
        QtCore.QMetaObject.invokeMethod(self, "_finish_answer",
                                        QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, reply))

    @QtCore.Slot(str)
    def _finish_answer(self, reply: str):
        self.view.append(f"<b>香蕉</b>：{reply}")
        self.btn.setEnabled(True); self.btn.setText("发送")
        self.input.setEnabled(True); self.input.setFocus()

# --------------------------- 入口 ---------------------------
def main():
    try:
        QtCore.QCoreApplication.setHighDpiScaleFactorRoundingPolicy(
            QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QtWidgets.QApplication([])
    w = PetWindow()
    scr = QtGui.QGuiApplication.primaryScreen().availableGeometry()
    w.move(scr.right() - w.width() - 40, scr.bottom() - w.height() - 120)
    w.show()
    app.exec()

if __name__ == "__main__":
    main()
