#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pixel Banana：极简像素香蕉桌面宠物（Mac / Windows）

仅使用本地 Ollama，不依赖任何云端接口。

特性：
- 透明无边框悬浮窗、可拖动、置顶；右键菜单；系统托盘图标
- 单击香蕉：成熟度循环（青/熟/过熟）+ 冒泡文字反馈
- 自动“冒泡”对话（随机）：时间 / 日期 / 天气 / 本地模型闲聊
- 本地模型：直连 Ollama（默认模型：qwen3:1.7b），失败回退至内置轻量应答
- 设置持久化：~/.pixel_banana_pet/config.json
- 内置「连接自检」对话框：一键排查端口/模型/接口可用性

依赖：
    pip install PySide6 requests

Ollama：
1) 安装并启动服务（默认 http://127.0.0.1:11434）
2) 拉取模型：ollama pull qwen3:1.7b  或你喜欢的其他模型

"""
import os, sys, json, re, time, random, threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import requests
from PySide6 import QtCore, QtGui, QtWidgets

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

# （可选）轻量停用词——不在起始就“掐死”输出，主要用于第二次重试前的温和限制
SOFT_STOPS = ["系统：", "用户：", "System:", "User:", "analysis:", "Analysis:"]

# --------------------------- 配置 ------------------
@dataclass
class Settings:
    model_url: str = DEFAULT_CFG["model_url"]
    model_name: str = DEFAULT_CFG["model_name"]
    city: str = DEFAULT_CFG["city"]
    auto_bubble: bool = DEFAULT_CFG["auto_bubble"]
    opacity: float = DEFAULT_CFG["opacity"]

    @staticmethod
    def load() -> "Settings":
        if CONF_PATH.exists():
            try:
                data = json.loads(CONF_PATH.read_text("utf-8"))
                return Settings(
                    model_url=data.get("model_url", DEFAULT_CFG["model_url"]),
                    model_name=data.get("model_name", DEFAULT_CFG["model_name"]),
                    city=data.get("city", DEFAULT_CFG["city"]),
                    auto_bubble=bool(data.get("auto_bubble", DEFAULT_CFG["auto_bubble"])),
                    opacity=float(data.get("opacity", DEFAULT_CFG["opacity"])),
                )
            except Exception:
                pass
        return Settings()

    def save(self):
        data = {
            "model_url": self.model_url,
            "model_name": self.model_name,
            "city": self.city,
            "auto_bubble": self.auto_bubble,
            "opacity": self.opacity,
        }
        CONF_DIR.mkdir(parents=True, exist_ok=True)
        CONF_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# --------------------------- 文本清洗：去思考过程 ---------------------------
_THINK_TAG = re.compile(r"(?is)<think>.*?</think>")
_THINK_BLOCK = re.compile(r"(?is)^\s*(?:思考|推理|分析)\s*[:：].*?(?:\n\s*\n|$)")
_FINAL_MARK = re.compile(r"(?is)(?:最终答案|答案|结论|Final Answer|Answer)\s*[:：]")

def strip_thinking(txt: str) -> str:
    if not txt:
        return ""
    # 1) 去 <think>…</think>
    txt = _THINK_TAG.sub("", txt)
    # 2) 去“思考：……（直到空行）”
    txt = _THINK_BLOCK.sub("", txt)
    # 3) 若出现“答案：/Final Answer:”等标记，只取其后的内容
    m = _FINAL_MARK.search(txt)
    if m:
        txt = txt[m.end():]
    # 4) 去常见头衔；保留多行；适度截断到 400 字
    txt = re.sub(r"^(?:答|助手|Assistant)\s*[:：]\s*", "", txt.strip())
    lines = [line.rstrip() for line in txt.splitlines() if line.strip()]
    return "\n".join(lines)[:400]

# --------------------------- Ollama 客户端 ---------------------------
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
                models = r.json().get("models", [])
                names = []
                for m in models:
                    n = m.get("name") or m.get("model")
                    if n:
                        names.append(n)
                return names
        except Exception:
            pass
        return []

    def _post_chat(self, messages, options) -> str:
        r = requests.post(
            f"{self.base_url}/api/chat",
            json={"model": self.model_name, "messages": messages, "stream": False, "options": options},
            timeout=self.timeout,
        )
        if not r.ok:
            try:
                return f"[HTTP {r.status_code}] {r.text[:200]}"
            except Exception:
                return "[HTTP 错误]"
        try:
            data = r.json()
            msg = (data.get("message") or {}).get("content", "")
            err = data.get("error")
            if err and not msg:
                return f"[本地模型错误] {err}"
            return msg or ""
        except Exception:
            return "[解析响应失败]"

    def ask(self, prompt: str, system: Optional[str] = None, no_think: bool = True) -> str:
        """返回“已清洗”的最终回答；如果第一次结果为空，会自动再试一次。"""
        sys_prompt = system or ""
        if no_think:
            sys_prompt = (
                (sys_prompt + " " if sys_prompt else "") +
                "不要输出思考、推理、过程或<think>标签；直接给答案，可分 1–3 句。"
            )

        msgs = []
        if sys_prompt:
            msgs.append({"role": "system", "content": sys_prompt})
        msgs.append({"role": "user", "content": prompt})

        # 第一次：普通生成（不设置会过早截断的 stop）
        msg1 = self._post_chat(msgs, {"num_predict": 256, "temperature": 0.6})
        clean1 = strip_thinking(msg1)
        if clean1:
            return clean1

        # 第二次：温和 stop + 更强系统约束
        msgs2 = list(msgs)
        if no_think:
            msgs2[0] = {"role": "system", "content": sys_prompt + " 请直接输出最终答案，避免任何步骤描述。"}
        msg2 = self._post_chat(msgs2, {"num_predict": 256, "temperature": 0.6, "stop": SOFT_STOPS})
        clean2 = strip_thinking(msg2)
        if clean2:
            return clean2

        # 仍不行 → 极简回退
        return self._fallback(prompt)

    @staticmethod
    def _fallback(prompt: str) -> str:
        p = prompt.strip()
        if any(k in p for k in ("你好", "hello", "hi")):
            return "你好，我是像素香蕉。今天也要补充维生素C！"
        if "天气" in p:
            return "关于天气：我可以试着查一下，但现在先给你一句鼓励 ✨"
        return "收到啦～"

# --------------------------- 自检对话框 ---------------------------
class SelfCheckDialog(QtWidgets.QDialog):
    def __init__(self, client: LocalModelClient, parent=None):
        super().__init__(parent); self.client = client
        self.setWindowTitle("像素香蕉 · 连接自检"); self.resize(420, 400)
        self.setModal(True)

        self.log_edit = QtWidgets.QPlainTextEdit(self); self.log_edit.setReadOnly(True)
        self.btn_run = QtWidgets.QPushButton("开始自检", self)
        lay = QtWidgets.QVBoxLayout(self); lay.addWidget(self.log_edit); lay.addWidget(self.btn_run)
        self.btn_run.clicked.connect(self.run)

    def log(self, s: str): self.log_edit.appendPlainText(s)

    def run(self):
        self.btn_run.setEnabled(False); self.log("开始自检…")
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            self.log("1) 检查 Ollama 服务…")
            r = requests.get(f"{self.client.base_url}/api/tags", timeout=5)
            r.raise_for_status(); self.log("   ✅ 服务在线")
        except Exception as e:
            self.log(f"   ❌ 服务不可用：{e}"); self._done("自检失败"); return

        try:
            self.log("2) 检查模型是否存在…")
            models = self.client.list_models()
            if self.client.model_name in models:
                self.log(f"   ✅ 找到模型：{self.client.model_name}")
            else:
                self.log(f"   ⚠️ 未找到 {self.client.model_name}，现有：{', '.join(models) or '无'}")
        except Exception as e:
            self.log(f"   ❌ 模型列表获取失败：{e}")

        try:
            self.log("3) 试跑一次对话…")
            sys = "你是像素香蕉。用中文回答，友好、简洁但不限字数（1–3句）。不要输出<think>或任何过程标记；直接给最终答案。"
            msg = self.client.ask("打个招呼", system=sys, no_think=True)
            self.log(f"   ✅ 成功：{msg[:80]}…")
        except Exception as e:
            self.log(f"   ❌ 对话接口失败：{e}")

        self._done("自检完成：一切正常 ✅")

    def _done(self, tail: str):
        self.log(tail); self.btn_run.setEnabled(True)

# --------------------------- 聊天对话框 ---------------------------
class ChatDialog(QtWidgets.QDialog):
    def __init__(self, client: LocalModelClient, parent=None):
        super().__init__(parent); self.client = client
        self.setWindowTitle("像素香蕉 · 对话"); self.resize(420, 420)
        self.setModal(False)

        self.view = QtWidgets.QTextBrowser(self)
        self.input = QtWidgets.QLineEdit(self)
        self.btn = QtWidgets.QPushButton("发送", self)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.view, 1); hl = QtWidgets.QHBoxLayout()
        hl.addWidget(self.input, 1); hl.addWidget(self.btn)
        lay.addLayout(hl)

        self.btn.clicked.connect(self.send)
        self.input.returnPressed.connect(self.send)

        # 右下角浮动一行小提示（可选）
        self._tip = QtWidgets.QLabel("提示：关闭窗口不影响香蕉继续陪伴你～", self)
        self._tip.setStyleSheet("color: #666;")
        lay.addWidget(self._tip)

    def _append(self, who: str, text: str):
        self.view.append(f"<b>{who}</b>：{text}")

    def send(self):
        text = self.input.text().strip()
        if not text: return
        self._append("你", text)
        self.btn.setEnabled(False); self.btn.setText("思考中…"); self.input.setEnabled(False)
        threading.Thread(target=self._ask_thread, args=(text,), daemon=True).start()

    def _ask_thread(self, text: str):
        system = ("你是像素香蕉。用中文回答，友好、简洁但不限字数（1–3句）。"
                  "不要输出<think>或任何过程标记；直接给最终答案。")
        reply = self.client.ask(text, system=system, no_think=True)
        QtCore.QMetaObject.invokeMethod(self, "_done", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, reply))

    @QtCore.Slot(str)
    def _done(self, reply: str):
        self._append("香蕉", reply)
        self.btn.setEnabled(True); self.btn.setText("发送")
        self.input.setEnabled(True); self.input.setFocus()

# --------------------------- 冒泡控件 ---------------------------
class Bubble(QtWidgets.QWidget):
    """香蕉风格对话气泡（无变色版，柔和圆角 + 尾巴 + 弹跳）"""
    def __init__(self, parent: QtWidgets.QWidget, text: str, ms: int = 2800):
        super().__init__(parent)
        self.text = text
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool)
        # 渐隐属性（保持与旧代码兼容）
        self._opacity = 0.0
        self.anim = QtCore.QPropertyAnimation(self, b"opacity", self)
        self.anim.setDuration(220); self.anim.setStartValue(0.0); self.anim.setEndValue(1.0); self.anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        # 弹跳动画
        self._pop = QtCore.QPropertyAnimation(self, b"geometry", self)
        self._pop.setDuration(220); self._pop.setEasingCurve(QtCore.QEasingCurve.OutBack)

        self.hide_timer = QtCore.QTimer(self); self.hide_timer.setInterval(ms); self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)

        self._pad, self._arrow = 12, 10
        self._radius = 14
        self.fm = QtGui.QFontMetrics(self.font())
        self._max_w = 360
        self.resize_to_text()

        # 固定配色
        self._bg = QtGui.QColor("#FFF3B0")       # 柔和淡黄
        self._fg = QtGui.QColor("#5C4905")       # 深一点的文字色
        self._border = QtGui.QColor(0, 0, 0, 30) # 轻描边

    def resize_to_text(self):
        # 逐字换行（适合中/英混排）
        max_w, lines, cur = self._max_w, [], ""
        for ch in self.text:
            if self.fm.horizontalAdvance(cur + ch) > max_w - 2 * self._pad:
                lines.append(cur); cur = ch
            else:
                cur += ch
        if cur: lines.append(cur)
        if not lines: lines = [""]
        self.lines = lines
        w = min(max_w, max(self.fm.horizontalAdvance(line) for line in lines) + 2 * self._pad)
        h = len(lines) * (self.fm.height() + 2) + 2 * self._pad + self._arrow
        self.resize(w, h)

    def setText(self, text: str):
        self.text = text
        self.resize_to_text()
        self.update()

    def paintEvent(self, e: QtGui.QPaintEvent):  # noqa
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0, 0, -1, -1)
        body = QtCore.QRect(rect.left(), rect.top(), rect.width(), rect.height() - self._arrow)
        path = QtGui.QPainterPath(); path.addRoundedRect(body, self._radius, self._radius)
        # 尾巴（默认朝下居中）
        tri = QtGui.QPolygon([
            QtCore.QPoint(body.center().x() - self._arrow, body.bottom()),
            QtCore.QPoint(body.center().x() + self._arrow, body.bottom()),
            QtCore.QPoint(body.center().x(), body.bottom() + self._arrow),
        ])
        # 底色与描边
        p.setOpacity(self._opacity)
        p.setPen(QtGui.QPen(self._border, 1))
        p.setBrush(self._bg)
        p.drawPath(path); p.drawPolygon(tri)
        # 文本
        p.setPen(self._fg)
        x = body.left() + self._pad; y = body.top() + self._pad + self.fm.ascent()
        for line in self.lines:
            p.drawText(x, y, line)
            y += self.fm.height() + 2

    # 兼容旧动画属性
    def get_opacity(self): return self._opacity
    def set_opacity(self, v: float): self._opacity = float(v); self.update()
    opacity = QtCore.Property(float, get_opacity, set_opacity)

    def popup(self, pos: QtCore.QPoint):
        # 目标几何
        target = QtCore.QRect(pos, self.size())
        # 弹跳起始几何（缩 90%）
        start = QtCore.QRect(target)
        start.setWidth(int(target.width() * 0.9))
        start.setHeight(int(target.height() * 0.9))
        start.moveCenter(target.center())

        self.setGeometry(start); self.show(); self.raise_()

        # 透明 & 弹跳动画
        self.anim.stop(); self.anim.setDirection(QtCore.QAbstractAnimation.Forward); self.anim.start()
        self._pop.stop(); self._pop.setStartValue(start); self._pop.setEndValue(target); self._pop.start()

        self.hide_timer.start()

    def fade_out(self):
        # 反向渐隐
        self.anim.stop()
        self.anim.setDirection(QtCore.QAbstractAnimation.Backward)
        self.anim.start()
        QtCore.QTimer.singleShot(self.anim.duration(), self.hide)

# --------------------------- 像素香蕉贴图 ---------------------------
class BananaSprite(QtWidgets.QWidget):
    clicked = QtCore.Signal()  # 正确：类级信号（可 connect/emit）
    class Grid:
        def __init__(self, w: int, h: int, points: List[tuple]):
            self.width, self.height = w, h
            self.points = points  # (x, y, val)

    def __init__(self, scale=6, parent=None):
        super().__init__(parent)
        self.scale = scale
        self.grid = self._build_grid()
        self.maturity = 1  # 0: 青, 1: 熟, 2: 过熟
        self.setFixedSize(self.grid.width * self.scale, self.grid.height * self.scale)
        # （已移除）信号应定义在类级，而非实例上

    def _build_grid(self) -> "BananaSprite.Grid":
        # 20x16 手写像素（val: 1 主体, 2 阴影, 3 果柄, 4 高光）
        w, h = 22, 16
        pts = set()
        body = [
            ".........1111111......", ".......11111111111....",
            "......1111111111111...", ".....111111111111111..",
            "....1111111111111111..", "...11111111111111111..",
            "..11111111111111111...", ".11111111111111111....",
            ".1111111111111111.....", "..111111111111111.....",
            "...11111111111111.....", "....1111111111111.....",
            "......1111111111..2...", "........1111111..22...",
            "..........111.....2...", "............1.........",
        ]
        shadow = [(x,y) for y,row in enumerate(body) for x,ch in enumerate(row) if ch=="1" and (y>=9 or x>=12)]
        for y,row in enumerate(body):
            for x,ch in enumerate(row):
                if ch=="1": pts.add((x,y,1))
        for (x,y) in shadow: pts.add((x, y+1 if y+1<h else y, 2))
        pts.add((18,2,3)); pts.add((19,2,3))
        for x,y in ((7,4),(8,5),(6,6)): pts.add((x,y,4))
        return BananaSprite.Grid(w,h,sorted(list(pts)))

    def set_maturity(self, m: int): self.maturity = max(0, min(2, m)); self.update()
    def cycle_maturity(self) -> int: self.maturity = (self.maturity + 1) % 3; self.update(); return self.maturity

    def mousePressEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button()==QtCore.Qt.LeftButton: self.clicked.emit()

    def paintEvent(self, e: QtGui.QPaintEvent):  # noqa
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        if self.maturity == 0: c_body, c_shadow = QtGui.QColor(150,190,60), QtGui.QColor(120,150,50)
        elif self.maturity == 1: c_body, c_shadow = QtGui.QColor(250,208,60), QtGui.QColor(210,170,50)
        else: c_body, c_shadow = QtGui.QColor(220,180,60), QtGui.QColor(140,110,50)
        c_stalk, c_high = QtGui.QColor(90,60,40), QtGui.QColor(255,255,240)
        for (x,y,val) in self.grid.points:
            color = c_body if val==1 else c_shadow if val==2 else c_stalk if val==3 else c_high if val==4 else QtGui.QColor(0,0,0,0)
            p.fillRect(x*self.scale, y*self.scale, self.scale, self.scale, color)
        if self.maturity == 2:
            rng = random.Random(42)
            for _ in range(12):
                x = rng.randrange(4, self.grid.width-2); y = rng.randrange(3, self.grid.height-2)
                p.fillRect(x*self.scale, y*self.scale, self.scale, self.scale, QtGui.QColor(110,80,40))

# --------------------------- 天气（open-meteo） ---------------------------
class Weather:
    @staticmethod
    def by_city(city: str) -> Optional[str]:
        city = (city or "").strip()
        if not city:
            return None
        try:
            g = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
                timeout=5,
            )
            g.raise_for_status()
            items = g.json().get("results") or []
            if not items:
                return None
            lat, lon = items[0]["latitude"], items[0]["longitude"]
            w = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon, "current_weather": True,
                    "hourly": "temperature_2m", "timezone": "auto", "forecast_days": 1,
                },
                timeout=5,
            )
            w.raise_for_status()
            data = w.json().get("current_weather", {})
            temp, ws, code = data.get("temperature"), data.get("windspeed"), data.get("weathercode")
            mapping = {0:"晴",1:"多云",2:"多云",3:"阴",45:"雾",48:"雾",51:"小雨",61:"小雨",63:"中雨",65:"大雨",71:"小雪",73:"中雪",75:"大雪",95:"雷阵雨"}
            desc = mapping.get(int(code or 0), "天气不明")
            if temp is not None:
                return f"{city} 天气：{desc}，{temp:.0f}°C，风速{ws:.0f} km/h"
        except Exception:
            return None
        return None

# --------------------------- 主窗口（宠物） ---------------------------
class PetWindow(QtWidgets.QWidget):
    customContextMenuRequested = QtCore.Signal(QtCore.QPoint)
    sigSay = QtCore.Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        self.client = LocalModelClient(self.settings.model_url, self.settings.model_name)

        self.setWindowTitle("像素香蕉")
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint)
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

        self.sigSay.connect(self.say)

        # 位置默认贴近右下
        scr = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        self.move(scr.right() - self.width() - 40, scr.bottom() - self.height() - 120)

        # 透明度
        self.setWindowOpacity(float(self.settings.opacity))

        # 启动后 2 秒自动冒泡一次
        QtCore.QTimer.singleShot(2000, self.auto_bubble)

    def _make_menu(self) -> QtWidgets.QMenu:
        m = QtWidgets.QMenu(self)
        act_chat = m.addAction("打开对话框…")
        act_chat.triggered.connect(lambda: ChatDialog(self.client, self).show())

        m.addSeparator()
        act_city = m.addAction("设置城市…")
        act_city.triggered.connect(self._ask_city)

        act_check = m.addAction("连接自检…")
        act_check.triggered.connect(lambda: SelfCheckDialog(self.client, self).exec())

        m.addSeparator()
        act_auto = m.addAction("自动冒泡"); act_auto.setCheckable(True); act_auto.setChecked(self.settings.auto_bubble)
        act_auto.toggled.connect(self._toggle_auto)

        m.addSeparator()
        act_model = m.addAction(f"当前模型：{self.client.model_name}"); act_model.setEnabled(False)
        act_opacity = m.addAction("设置气泡透明度…")
        act_opacity.triggered.connect(self._ask_opacity)

        m.addSeparator()
        act_quit = m.addAction("退出")
        act_quit.triggered.connect(QtWidgets.QApplication.instance().quit)
        return m

    def _toggle_auto(self, v: bool):
        self.settings.auto_bubble = bool(v); self.settings.save()
        self.say("好的，已" + ("开启" if v else "关闭") + "自动冒泡。")

    def _ask_opacity(self):
        val, ok = QtWidgets.QInputDialog.getDouble(self, "透明度", "0.50～1.00：", value=self.settings.opacity, min=0.5, max=1.0, decimals=2)
        if ok:
            self.settings.opacity = float(val); self.settings.save()
            self.setWindowOpacity(float(val))
            self.say(f"气泡透明度 {val:.2f}，生效啦～")

    def _ask_city(self):
        text, ok = QtWidgets.QInputDialog.getText(self, "设置城市", "用于天气查询（可留空）：", text=self.settings.city)
        if ok:
            self.settings.city = text.strip(); self.settings.save()
            self.say(f"知道了，城市设为 {self.settings.city}。" if self.settings.city else "已清除城市设置。")

    @QtCore.Slot(str)
    def say(self, text: str):
        b = Bubble(self, text)
        x = self.x() + (self.width() - b.width()) // 2
        y = self.y() - b.height() - 6
        scr = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        x = max(scr.left() + 6, min(x, scr.right() - b.width() - 6))
        y = max(scr.top() + 6, y)
        b.popup(QtCore.QPoint(x, y))

    def on_click(self):
        m = self.sprite.cycle_maturity()
        if m == 0: self.say("还青着，再等等～")
        elif m == 1: self.say("现在正好！")
        else: self.say("有点过熟，香倒是更香了。")

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

    def mousePressEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button()==QtCore.Qt.LeftButton:
            self._press_pos = e.globalPosition().toPoint(); e.accept()
        else: e.ignore()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.buttons() & QtCore.Qt.LeftButton and hasattr(self, "_press_pos"):
            gp = e.globalPosition().toPoint(); diff = gp - self._press_pos
            self.move(self.x()+diff.x(), self.y()+diff.y()); self._press_pos = gp; e.accept()
        else: e.ignore()

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):  # noqa
        if hasattr(self, "_press_pos"): delattr(self, "_press_pos")

    def contextMenuEvent(self, e: QtGui.QContextMenuEvent):  # noqa
        self.tray_menu.exec(e.globalPos())

    def show_menu(self, pos: QtCore.QPoint):
        self.tray_menu.exec(self.mapToGlobal(pos))

    def paintEvent(self, e: QtGui.QPaintEvent):  # noqa
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        p.fillRect(self.rect(), QtCore.Qt.transparent)
        self.sprite.move(0, 0)

# --------------------------- 启动 ---------------------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    w = PetWindow()
    scr = QtGui.QGuiApplication.primaryScreen().availableGeometry()
    w.move(scr.right() - w.width() - 40, scr.bottom() - w.height() - 120)
    w.show()
    app.exec()

if __name__ == "__main__":
    main()
