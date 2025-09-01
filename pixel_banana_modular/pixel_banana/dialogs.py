from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets
from .textclean import strip_thinking
import difflib, time, threading, requests
from datetime import datetime


class SelfCheckDialog(QtWidgets.QDialog):
    def __init__(self, settings, client, parent=None):
        super().__init__(parent)
        self.settings, self.client = settings, client
        self.setWindowTitle("像素香蕉 · 连接自检")
        self.resize(560, 440)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.view = QtWidgets.QTextEdit(self)
        self.view.setReadOnly(True)
        self.btn_run = QtWidgets.QPushButton("重新测试")
        self.btn_close = QtWidgets.QPushButton("关闭")
        self.btn_run.clicked.connect(self.start)
        self.btn_close.clicked.connect(self.accept)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.view)
        hl = QtWidgets.QHBoxLayout()
        hl.addStretch(1)
        hl.addWidget(self.btn_run)
        hl.addWidget(self.btn_close)
        lay.addLayout(hl)
        self.start()

    def log(self, s: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.view.append(f"[{ts}] {s}")
        self.view.moveCursor(QtGui.QTextCursor.End)

    def start(self):
        self.view.clear()
        self.log("开始自检…")
        self.btn_run.setEnabled(False)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        url = self.settings.model_url.rstrip("/")
        name = self.settings.model_name
        try:
            t0 = time.perf_counter()
            r = requests.get(f"{url}/api/tags", timeout=5)
            dt = (time.perf_counter() - t0) * 1000
            if not r.ok:
                self._done(f"无法连接 Ollama（HTTP {r.status_code}）：{r.text[:200]}")
                return
            self.log(f"✔ /api/tags 可达，{dt:.0f} ms")
            models = r.json().get("models") or r.json().get("data") or []
            names = [
                m.get("name") or m.get("model")
                for m in models
                if (m.get("name") or m.get("model"))
            ]
            if name in names:
                self.log(f"✔ 已安装模型：{name}")
            else:
                self.log(f"✖ 未找到模型：{name}")
                if names:
                    cand = difflib.get_close_matches(name, names, n=3, cutoff=0.3)
                    if cand:
                        self.log("  可能想要的是：" + ", ".join(cand))
                self._done("请 `ollama pull` 对应模型，或在菜单里修改模型名。")
                return
        except Exception as ex:
            self._done(f"✖ 无法访问 Ollama：{ex}")
            return

        try:
            t1 = time.perf_counter()
            payload = {
                "model": name,
                "messages": [{"role": "user", "content": "只回：香蕉OK"}],
                "stream": False,
                "keep_alive": 0,
            }
            r = requests.post(f"{url}/api/chat", json=payload, timeout=12)
            dt = (time.perf_counter() - t1) * 1000
            if not r.ok:
                self._done(f"✖ /api/chat 失败（HTTP {r.status_code}）：{r.text[:200]}")
                return
            raw = (r.json().get("message") or {}).get("content", "")
            clean = strip_thinking(raw) or raw[:24]
            self.log(f"✔ /api/chat 正常，用时 {dt:.0f} ms；回声：{clean!r}")
        except Exception as ex:
            self._done(f"✖ /api/chat 调用异常：{ex}")
            return

        self._done("自检完成：一切正常 ✅")

    def _done(self, tail: str):
        self.log(tail)
        self.btn_run.setEnabled(True)


class ChatDialog(QtWidgets.QDialog):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("像素香蕉 · 对话")
        self.resize(420, 420)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.view = QtWidgets.QTextEdit(self)
        self.view.setReadOnly(True)
        self.input = QtWidgets.QLineEdit(self)
        self.btn = QtWidgets.QPushButton("发送")
        self.btn.clicked.connect(self.on_send)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(self.view)
        hl = QtWidgets.QHBoxLayout()
        hl.addWidget(self.input, 1)
        hl.addWidget(self.btn)
        lay.addLayout(hl)
        self.input.returnPressed.connect(self.on_send)
        self._append("系统", "聊点什么？")

    def _append(self, who: str, text: str):
        self.view.append(f"<b>{who}</b>：{QtGui.QGuiApplication.translate('', text)}")

    def on_send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append("你", text)
        self.btn.setEnabled(False)
        self.btn.setText("思考中…")
        self.input.setEnabled(False)
        import threading

        threading.Thread(target=self._ask_thread, args=(text,), daemon=True).start()

    def _ask_thread(self, text: str):
        system = (
            "你是像素香蕉。用中文回答，友好、简洁但不限字数（1–3句）。"
            "不要输出<think>或任何过程标记。"
        )
        reply = self.client.ask(text, system=system, no_think=True)
        QtCore.QMetaObject.invokeMethod(
            self, "_finish_answer", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, reply)
        )

    @QtCore.Slot(str)
    def _finish_answer(self, reply: str):
        self.view.append(f"<b>香蕉</b>：{reply}")
        self.btn.setEnabled(True)
        self.btn.setText("发送")
        self.input.setEnabled(True)
        self.input.setFocus()
