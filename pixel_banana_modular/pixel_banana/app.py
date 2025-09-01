from __future__ import annotations
import random, threading
from datetime import datetime
from PySide6 import QtCore, QtGui, QtWidgets
from .settings import Settings
from .client import LocalModelClient
from .widgets import BananaSprite, InputBar, PrettyBubble, banana_pixmap
from .dialogs import ChatDialog, SelfCheckDialog
from .weather import Weather


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

        icon = QtGui.QIcon(banana_pixmap(32))
        self.setWindowIcon(icon)

        self.tray = QtWidgets.QSystemTrayIcon(icon, self)
        self.tray.setToolTip("像素香蕉")
        self.tray.setIcon(icon)
        self.tray.setVisible(True)
        self.tray_menu = self._make_menu()
        self.tray.setContextMenu(self.tray_menu)

        self.auto_timer = QtCore.QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.timeout.connect(self.auto_bubble)
        if self.settings.auto_bubble:
            self._schedule_auto()

        self.sigSay.connect(self.say)
        QtCore.QTimer.singleShot(
            800, lambda: self.say("你好，我是像素香蕉，单击我可以在底部输入~")
        )
        self.setWindowOpacity(self.settings.opacity)

        self.input_bar = InputBar(None)
        self.input_bar.sigSubmit.connect(self._handle_user_submit)
        self._pretty = PrettyBubble(None)
        self._pretty.set_typing(True)

        self._app.aboutToQuit.connect(self._on_about_to_quit)

    def _on_about_to_quit(self):
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
            self.say(f"好的，之后用 {self.settings.model_name}。")

    def change_city(self):
        cur = self.settings.city
        text, ok = QtWidgets.QInputDialog.getText(
            self, "设置城市", "用于天气查询（示例：南京 / Beijing）：", text=cur
        )
        if ok:
            self.settings.city = text.strip()
            self.settings.save()
            self.say(
                f"知道了，城市设为 {self.settings.city}。"
                if self.settings.city
                else "已清除城市设置。"
            )

    @QtCore.Slot(str)
    def say(self, text: str):
        self._pretty.popup(text, anchor_rect=self.frameGeometry(), prefer="right")

    def on_click(self):
        self.input_bar.show_at_bottom()

    def _schedule_auto(self):
        self.auto_timer.start(random.randint(30_000, 75_000))

    def auto_bubble(self):
        if not self.settings.auto_bubble:
            return
        choice = random.random()
        if choice < 0.3:
            self.say(f"今天是 {datetime.now().strftime('%Y-%m-%d, %H:%M')}")
        elif choice < 0.55:
            text = Weather.by_city(self.settings.city) if self.settings.city else None
            self.say(text or "天气如何？要不要我给你一点阳光能量☀️")
        else:
            if self.client.is_available():

                def _work():
                    prompt = (
                        "生成一句中文短句（8-18字），作为温柔且有点俏皮的提醒，主题可在健康、效率或休息中任选。"
                        "不要表情符号，不要标点以外的装饰，不要输出任何思考过程。"
                    )
                    system = "你是像素香蕉，用中文简短自然回复（≤1句）。"
                    reply = self.client.ask(prompt, system=system, no_think=True)
                    self.sigSay.emit(reply or "喝口水，眨眨眼，再继续。")

                threading.Thread(target=_work, daemon=True).start()
            else:
                self.say("喝口水，眨眨眼，再继续。")
        self._schedule_auto()

    def _handle_user_submit(self, user_text: str):
        def _ask():
            system = (
                "你是像素香蕉。用中文回答，友好、简洁但不限字数（1–3句）。"
                "不要输出<think>或任何过程标记。"
            )
            # call client in thread
            reply = self.client.ask(user_text, system=system, no_think=True)
            self.sigSay.emit(reply)

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
