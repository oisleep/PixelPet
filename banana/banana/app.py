from __future__ import annotations
import random, threading
from datetime import datetime
from PySide6 import QtCore, QtGui, QtWidgets
from .settings import Settings
from .client import LocalModelClient
from .widgets import BananaSprite, InputBar, PrettyBubble, banana_pixmap
from .dialogs import ChatDialog, SelfCheckDialog
from . import weather
import random, threading, time

# 新增：兜底清理需要
import re
from .textclean import strip_thinking

# 新增：快捷键所需
import sys
from PySide6.QtGui import QShortcut, QKeySequence

# 全局热键（Win/Linux）：pyqtkeybind；macOS 暂不启用全局（避免与原生事件循环冲突）
try:
    from pyqtkeybind import keybinder
    HAS_KEYBINDER = True
except Exception:
    HAS_KEYBINDER = False


class PetWindow(QtWidgets.QWidget):
    customContextMenuRequested = QtCore.Signal(QtCore.QPoint)
    sigSay = QtCore.Signal(str)

    def __init__(self, app: QtWidgets.QApplication):
        super().__init__()
        self._app = app
        self.settings = Settings.load()
        self.client = LocalModelClient(
            self.settings.model_url, self.settings.model_name
        )

        self.setWindowTitle("不拿拿")
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

        icon = QtGui.QIcon(banana_pixmap(32))
        self.setWindowIcon(icon)

        self.tray = QtWidgets.QSystemTrayIcon(icon, self)
        self.tray.setToolTip("不拿拿")
        self.tray.setIcon(icon)
        self.tray.setVisible(True)
        self.tray_menu = self._make_menu()
        self.tray.setContextMenu(self.tray_menu)
        # --- 自动冒泡频率与静默策略（毫秒）---
        self.AUTO_MIN_MS = 120_000      # 2 分钟
        self.AUTO_MAX_MS = 300_000      # 5 分钟
        self.SILENCE_AFTER_CHAT = 120_000   # 主动对话后静默 2 分钟
        self.WEATHER_COOLDOWN = 600_000   # 天气至少间隔 10 分钟
        self.RANDOM_COOLDOWN  = 120_001   # 随机话至少间隔 2 分钟

        # --- 运行时状态 ---
        self._busy_until_ms   = 0       # 在这之前一律不冒泡
        self._last_weather_ms = 0
        self._last_random_ms  = 0

        self.auto_timer = QtCore.QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self.auto_bubble)
        if self.settings.auto_bubble:
            self._schedule_auto()

        self.sigSay.connect(self.say)
        QtCore.QTimer.singleShot(
            800,
            lambda: self.say(
                "Oi~ 我是你的专属助理，你可以叫我不拿拿，点击我可以和我对话喔~"
            ),
        )
        self.setWindowOpacity(self.settings.opacity)

        self.input_bar = InputBar(None)
        self.input_bar.sigSubmit.connect(self._handle_user_submit)
        self._pretty = PrettyBubble(None)
        self._pretty.set_typing(True)

        # ——（Win/Linux）初始化全局热键库——
        if HAS_KEYBINDER and sys.platform != "darwin":
            try:
                keybinder.init()
            except Exception:
                HAS_KEYBINDER = False

        # —— 安装快捷键（应用内 + 可选全局）——
        self._install_hotkey()

        self._app.aboutToQuit.connect(self._on_about_to_quit)

    def _on_about_to_quit(self):
        # 退出清理全局热键（若有）
        if HAS_KEYBINDER and sys.platform != "darwin":
            try:
                keybinder.unregister_hotkey(int(self.winId()), getattr(self, "_hotkey_seq", self._default_hotkey()))
                keybinder.clean()
            except Exception:
                pass

        if self.settings.unload_on_exit:
            threading.Thread(target=self.client.unload, daemon=True).start()

    def _make_menu(self) -> QtWidgets.QMenu:
        m = QtWidgets.QMenu()
        m.addAction("打开聊天窗…", self.open_chat)
        m.addAction("连接自检…", self.open_selfcheck)
        m.addSeparator()
        act_toggle = m.addAction("切换自动冒泡", self.toggle_auto)
        act_toggle.setCheckable(True)
        act_toggle.setChecked(self.settings.auto_bubble)
        sub = m.addMenu("透明度")
        for pct in (100, 95, 90, 85, 80):
            act = sub.addAction(f"{pct}%")
            act.triggered.connect(lambda _=False, v=pct: self.set_opacity_pct(v))
        m.addSeparator()
        act_unload = m.addAction("退出时卸载模型", lambda: self.toggle_unload_on_exit())
        act_unload.setCheckable(True)
        act_unload.setChecked(self.settings.unload_on_exit)
        m.addAction("设置模型名…", self.change_model)
        m.addAction("设置城市（天气）…", self.change_city)
        # 新增：设置快捷键（可修改 Ctrl+Alt+Space / Ctrl+Option+Space 等）
        m.addAction("设置快捷键…", self.change_hotkey)
        m.addSeparator()
        m.addAction("退出", QtWidgets.QApplication.quit)
        return m

    def toggle_unload_on_exit(self):
        self.settings.unload_on_exit = not self.settings.unload_on_exit
        self.settings.save()
        self.say(
            "已开启：退出时卸载模型"
            if self.settings.unload_on_exit
            else "已关闭：退出时卸载模型"
        )

    def show_menu(self, global_pos: QtCore.QPoint):
        self._make_menu().exec(global_pos)

    def open_chat(self):
        ChatDialog(self.client, self).exec()

    def open_selfcheck(self):
        SelfCheckDialog(self.settings, self.client, self).exec()

    def toggle_auto(self):
        self.settings.auto_bubble = not self.settings.auto_bubble
        self.settings.save()
        if self.settings.auto_bubble:
            self._schedule_auto()
        else:
            self.auto_timer.stop()

    def set_opacity_pct(self, pct: int):
        self.settings.opacity = max(0.3, min(1.0, pct / 100.0))
        self.settings.save()
        self.setWindowOpacity(self.settings.opacity)

    def change_model(self):
        cur = self.settings.model_name
        text, ok = QtWidgets.QInputDialog.getText(
            self, "设置模型名", "Ollama 模型名：", text=cur
        )
        if ok and text.strip():
            self.settings.model_name = text.strip()
            self.settings.save()
            self.say(f"好的，之后我会调用 {self.settings.model_name}。")

    def change_city(self):
        cur = self.settings.city
        text, ok = QtWidgets.QInputDialog.getText(
            self, "设置城市", "用于天气查询（示例：南京 / Beijing）：", text=cur
        )
        if ok:
            self.settings.city = text.strip()
            self.settings.save()
            self.say(
                f"好的我知道你在 {self.settings.city} 咯。"
                if self.settings.city
                else "已清除城市设置。"
            )

    # ===== 快捷键：默认、候选、安装、更改、触发 =====

    def _default_hotkey(self) -> str:
        # 避开系统常用快捷键：macOS Spotlight/Ctrl+Space、Win Alt+Space 等
        if sys.platform == "darwin":
            return "Ctrl+Option+Space"   # macOS
        return "Ctrl+Alt+Space"          # Windows/Linux

    def _fallback_hotkeys(self):
        # 平台化的候选列表，尽量避开输入法/系统快捷键
        if sys.platform == "darwin":
            return ["Ctrl+Option+`", "Ctrl+Option+;", "Ctrl+Shift+`"]
        else:
            return ["Ctrl+Alt+`", "Ctrl+Alt+;", "Ctrl+Shift+;"]

    def _install_hotkey(self, seq: str | None = None):
        """安装应用内快捷键 +（若可用）Win/Linux 全局快捷键；自动避让并提示"""
        want = (seq or self._default_hotkey()).strip()

        # —— 应用内快捷键（总能生效）——
        try:
            if hasattr(self, "_shortcut") and self._shortcut is not None:
                try:
                    self._shortcut.activated.disconnect(self._toggle_input)
                except Exception:
                    pass
                self._shortcut.deleteLater()
        except Exception:
            pass
        self._shortcut = QShortcut(QKeySequence(want), self)
        self._shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        self._shortcut.activated.connect(self._toggle_input)

        # —— Win/Linux：使用 pyqtkeybind 注册全局快捷键，自动尝试候选 —— #
        global_ok = False
        used = want
        if HAS_KEYBINDER and sys.platform != "darwin":
            candidates = [want] + [h for h in self._fallback_hotkeys() if h != want]
            wid = int(self.winId())  # Qt 原生窗口句柄
            for cand in candidates:
                try:
                    # 先卸掉之前的（如果有）
                    try:
                        keybinder.unregister_hotkey(wid, used)
                    except Exception:
                        pass
                    keybinder.register_hotkey(wid, cand, self._toggle_input)
                    global_ok, used = True, cand
                    break
                except Exception:
                    continue

        # —— 结果提示（桌面气泡）——
        self._hotkey_seq = used
        if global_ok:
            self.say(f"已注册全局快捷键：{used}" if used == want else f"原快捷键被占用，已切换为全局：{used}")
        else:
            note = "（macOS 或未安装 pyqtkeybind）" if sys.platform == "darwin" or not HAS_KEYBINDER \
                   else "（系统占用，已退回应用内）"
            self.say(f"仅应用内快捷键生效：{used} {note}")

    def change_hotkey(self):
        cur = getattr(self, "_hotkey_seq", self._default_hotkey())
        text, ok = QtWidgets.QInputDialog.getText(
            self, "设置快捷键", "示例：Ctrl+Alt+Space / Ctrl+Option+Space", text=cur
        )
        if ok and text.strip():
            self._install_hotkey(text.strip())
            self.say(f"快捷键已设置为 {text.strip()}。")

    @QtCore.Slot()
    def _toggle_input(self):
        # 已在输入 → 聚焦；否则直接唤起
        if self.input_bar.isVisible():
            self.input_bar.raise_()
            self.input_bar.activateWindow()
            self.input_bar.setFocus()
        else:
            self.on_click()

    @QtCore.Slot(str)
    def say(self, text: str):
        # 兜底清理：先用 strip_thinking，再剥“说话人：”前缀，保证桌面气泡不带“香蕉：/不拿拿：”
        t = strip_thinking(text) or (text or "")
        t = re.sub(r'^(?:香蕉 Emoji|香蕉|香蕉Emoji|不拿拿|助手|Assistant)\s*[:：]\s*', '', t.strip(), flags=re.I)
        self._pretty.popup(t, anchor_rect=self.frameGeometry(), prefer="right")

    def on_click(self):
        # 用户准备说话 → 先静默一段时间
        self._busy_until_ms = int(time.time() * 1000) + self.SILENCE_AFTER_CHAT
        self.auto_timer.stop()
        self.input_bar.show_at_bottom()

        # 保证唤起后可直接输入
        try:
            self.input_bar.activateWindow()
            QtWidgets.QApplication.setActiveWindow(self.input_bar)
        except Exception:
            pass
        QtCore.QTimer.singleShot(0, lambda: (
            self.input_bar.edit.setFocus(QtCore.Qt.ShortcutFocusReason),
            self.input_bar.edit.selectAll()
        ))

    def _schedule_auto(self):
        self.auto_timer.start(random.randint(self.AUTO_MIN_MS, self.AUTO_MAX_MS))

    def auto_bubble(self):
        if not self.settings.auto_bubble:
            return

        now = int(time.time() * 1000)
        # 只要输入条在，或者还在静默窗口内，就不冒泡
        if self.input_bar.isVisible() or now < self._busy_until_ms:
            self._schedule_auto()
            return

        choice = random.random()
        did = False

        # 1) 时间播报（仍可偶尔出现）
        if choice < 0.25:
            self.say(f"现在是 {datetime.now().strftime('%Y-%m-%d, %H:%M')} 咯~")
            did = True

        # 2) 天气（至少 30 分钟一次）
        elif choice < 0.40 and now - self._last_weather_ms >= self.WEATHER_COOLDOWN:
            if self.settings.city:
                text = weather.by_city(self.settings.city)
                if text:
                    self.say(text)
                    did = True
            if did:
                self._last_weather_ms = now

        # 3) 随机小提醒（至少 60 分钟一次）
        elif now - self._last_random_ms >= self.RANDOM_COOLDOWN:
            if self.client.is_available():
                def _work():
                    prompt = (
                        "生成一句中文短句，语气温柔风趣，主题在健康/效率/休息任选；"
                        "允许使用1个合适的emoji；不要夸张语气词；不要输出任何思考过程。"
                    )
                    system = "请注意，与你对话的用户是Barbara，你长得像一个香蕉，你的名字叫‘不拿拿’；你要为Barbara服务，Barbara是最可爱的，要耐心点对她。用中文简短自然回复。"
                    reply = self.client.ask(prompt, system=system, no_think=True)
                    self.sigSay.emit(reply or "喝口水，眨眨眼，再继续。")
                threading.Thread(target=_work, daemon=True).start()
            else:
                self.say("喝口水，眨眨眼，再继续。")
            did = True
            self._last_random_ms = now

        # 如果本轮所有分支都被“冷却”挡住，就安静地改天再来
        if not did:
            pass

        self._schedule_auto()

    def _handle_user_submit(self, user_text: str):
        def _ask():
            system = (
                "角色：你是Barbara的专属 AI 助手，你长得像一个香蕉，你叫‘不拿拿’；你要为Barbara服务，Barbara是最可爱的，要耐心点对她。第一人称=助手，第二人称=用户（Barbara/小巴）"
                "语气：温柔、克制、风趣一点点；不卖惨不撒娇；鼓励但不空话"
                "句式：短句优先、信息先行；1–3句为宜；必要时给1条可执行建议"
                "称呼：优先用“Barbara”"
                "Emoji：每条 ≤ 1 个，恰当即可；不用“！！！”、“~~~”"
                "禁用词：主人、亲亲、宝宝、小仙女、美女、抱抱、么么哒、土味情话"
                "身份问答示例（严格遵循）："
                "用户：我是谁？ → 助手：你是 Barbara。"
                "用户：你是谁？ → 助手：我是不拿拿。"
                "输出：只给最终答案，不输出思考/过程/标签"
            )
            # call client in thread
            reply = self.client.ask(user_text, system=system, no_think=True)
            self.sigSay.emit(reply)
            # 回复已给出 → 静默持续一段时间，然后再恢复自动冒泡
            self._busy_until_ms = int(time.time() * 1000) + self.SILENCE_AFTER_CHAT

            def _resume():
                # 静默到点，立刻恢复自动冒泡节奏（1–2 分钟内来一句）
                self._busy_until_ms = 0
                self.auto_timer.start(random.randint(60_000, 120_000))

            QtCore.QTimer.singleShot(self.SILENCE_AFTER_CHAT, _resume)

        threading.Thread(target=_ask, daemon=True).start()

    def mousePressEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button() == QtCore.Qt.LeftButton:
            self._press_pos = e.globalPosition().toPoint()
            e.accept()
        else:
            e.ignore()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.buttons() & QtCore.Qt.LeftButton and hasattr(self, "_press_pos"):
            gp = e.globalPosition().toPoint()
            diff = gp - self._press_pos
            if diff.manhattanLength() >= 2:
                self.move(self.pos() + diff)
                self._press_pos = gp
