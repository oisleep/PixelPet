from __future__ import annotations
from typing import Optional
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import (
    Qt,
    QRect,
    QRectF,
    QSize,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPainterPath,
    QPen,
    QFontMetrics,
    QGuiApplication,
)
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QGraphicsDropShadowEffect
import sys, time

import re
from PySide6.QtGui import QTextDocument
from PySide6 import QtCore, QtGui


# -------- Icon --------
def banana_pixmap(size: int = 32) -> QtGui.QPixmap:
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)

    # 画布留一点边距，方便不同尺寸下的视觉
    margin = max(1, size // 16)
    rect = QtCore.QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

    # 用 0–100 的归一坐标来描述香蕉曲线
    def X(x): return rect.left() + rect.width()  * (x / 100.0)
    def Y(y): return rect.top()  + rect.height() * (y / 100.0)

    # 香蕉主体（两段三次样条，弯月形）
    path = QtGui.QPainterPath()
    path.moveTo(X(12), Y(62))
    path.cubicTo(X(15), Y(36), X(52), Y(24), X(86), Y(40))
    path.cubicTo(X(70), Y(70), X(42), Y(88), X(20), Y(86))
    path.cubicTo(X(12), Y(80), X(10), Y(70), X(12), Y(62))

    # 内填充：明→暗的线性渐变，更像熟香蕉
    grad = QtGui.QLinearGradient(X(20), Y(40), X(80), Y(86))
    grad.setColorAt(0.00, QtGui.QColor(255, 236, 110))  # 亮黄高光
    grad.setColorAt(0.60, QtGui.QColor(250, 208,  60))  # 主体黄
    grad.setColorAt(1.00, QtGui.QColor(225, 178,  40))  # 暗部
    p.fillPath(path, grad)

    # 外轮廓：偏棕的描边
    pen = QtGui.QPen(QtGui.QColor(155, 115, 30))
    pen.setWidthF(max(1.0, size / 48.0))
    p.setPen(pen)
    p.drawPath(path)

    # 侧边高光：一条柔和的亮线
    hpath = QtGui.QPainterPath()
    hpath.moveTo(X(28), Y(56))
    hpath.cubicTo(X(38), Y(38), X(58), Y(34), X(76), Y(46))
    hpen = QtGui.QPen(QtGui.QColor(255, 255, 245, 150))
    hpen.setWidthF(max(1.0, size / 60.0))
    p.setPen(hpen)
    p.drawPath(hpath)

    # 果柄（蒂）
    stem = QtGui.QPainterPath()
    stem.addRoundedRect(QtCore.QRectF(X(82), Y(36), rect.width() * 0.08, rect.height() * 0.10),
                        max(1.0, size / 32.0), max(1.0, size / 32.0))
    p.fillPath(stem, QtGui.QColor(90, 60, 40))
    p.setPen(QtGui.QPen(QtGui.QColor(70, 45, 30)))
    p.drawPath(stem)

    # 尾端的小深色点
    tip = QtGui.QPainterPath()
    tip.addEllipse(QtCore.QRectF(X(16) - size / 100.0, Y(84) - size / 100.0,
                                 rect.width() * 0.06, rect.height() * 0.06))
    p.fillPath(tip, QtGui.QColor(120, 80, 20, 230))

    p.end()
    return pm


# -------- Bubbles --------
class PrettyBubble(QWidget):
    BG_COLOR = QColor("#FFF3B0")
    FG_COLOR = QColor("#5C4905")
    BORDER_COLOR = QColor(0, 0, 0, 30)

    def __init__(self, parent=None):
        super().__init__(
            parent,
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.setMouseTracking(True)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        f = self._label.font()
        f.setPointSizeF(11.5)
        self._label.setFont(f)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.addWidget(self._label)

        if sys.platform.startswith("win"):
            self.setGraphicsEffect(None)
        else:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(24)
            shadow.setOffset(0, 6)
            shadow.setColor(QColor(0, 0, 0, 80))
            self.setGraphicsEffect(shadow)

        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(220)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

        self._pop = QPropertyAnimation(self, b"geometry", self)
        self._pop.setDuration(220)
        self._pop.setEasingCurve(QEasingCurve.OutBack)

        self._tail_size = 10
        self._radius = 14
        self._tail_side = "bottom"
        self._min_width = 140
        self._max_width = 360
        self._max_html_width = 420  # ⬅︎ HTML 卡片最大宽（新）
        self._last_geo = None

        self._auto_close_ms = 5000
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.fade_out)

        self._typing = False
        self._full_text = ""
        self._type_idx = 0
        self._type_timer = QTimer(self)
        self._type_timer.setInterval(16)
        self._type_timer.timeout.connect(self._type_step)

        pal = self._label.palette()
        pal.setColor(self._label.foregroundRole(), self.FG_COLOR)
        self._label.setPalette(pal)

    def set_typing(self, enabled: bool):
        self._typing = bool(enabled)

    def set_max_width(self, w: int):
        self._max_width = max(200, int(w))

    def set_auto_close_ms(self, ms: int):
        self._auto_close_ms = max(0, int(ms))

    def popup(self, text: str, anchor_rect: QtCore.QRect, prefer="right"):
        screen = (
            QGuiApplication.screenAt(anchor_rect.center())
            or (self.windowHandle().screen() if self.windowHandle() else None)
            or QGuiApplication.primaryScreen()
        )
        geo = screen.availableGeometry()
        self._last_geo = geo

        # 仅给「文本」用较大的上限；HTML 的宽度在 _prepare_text 里已经单独限制了
        self.set_max_width(int(geo.width() * 0.60))

        self._prepare_text(text)
        hint = self._size_hint_for(self._label.text() if not self._typing else "")
        geo_rect = self._suggest_geometry(anchor_rect, hint, prefer)

        start = QtCore.QRect(geo_rect)
        start.setWidth(int(geo_rect.width() * 0.9))
        start.setHeight(int(geo_rect.height() * 0.9))
        start.moveCenter(geo_rect.center())

        self.setGeometry(start)
        self.setWindowOpacity(0.0)
        self.show()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._pop.stop()
        self._pop.setStartValue(start)
        self._pop.setEndValue(geo_rect)
        plain = re.sub(r"<[^>]+>", "", text or "")
        chars = len(plain.strip())
        is_html = bool(re.search(r"</?\w+[^>]*>", text or ""))
        typing_ms = (
            2200 if (self._typing and not is_html) else 0
        )  # 你的打字动画大约 2.2s
        read_ms = max(2500, min(16000, int(chars * 55)))  # ~55ms/字，夹 2.5–16s
        dur = max(self._auto_close_ms, typing_ms + read_ms)  # 短文仍保留默认最短
        if self._auto_close_ms > 0:
            self._close_timer.start(dur)

    def fade_out(self):
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(180)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self.hide)
        anim.start()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        body = QtCore.QRectF(rect)
        if self._tail_side == "bottom":
            body.adjust(0, 0, 0, -self._tail_size)
        elif self._tail_side == "top":
            body.adjust(0, self._tail_size, 0, 0)
        elif self._tail_side == "right":
            body.adjust(0, 0, -self._tail_size, 0)
        elif self._tail_side == "left":
            body.adjust(self._tail_size, 0, 0, 0)

        path = QPainterPath()
        path.addRoundedRect(body, self._radius, self._radius)
        tail = QPainterPath()
        ts = float(self._tail_size)
        tw = ts * 2.0
        if self._tail_side in ("bottom", "top"):
            cx = body.center().x()
            if self._tail_side == "bottom":
                tail.moveTo(cx - tw / 2, body.bottom())
                tail.lineTo(cx + tw / 2, body.bottom())
                tail.lineTo(cx, body.bottom() + ts)
            else:
                tail.moveTo(cx - tw / 2, body.top())
                tail.lineTo(cx + tw / 2, body.top())
                tail.lineTo(cx, body.top() - ts)
        else:
            cy = body.center().y()
            if self._tail_side == "right":
                tail.moveTo(body.right(), cy - tw / 2)
                tail.lineTo(body.right(), cy + tw / 2)
                tail.lineTo(body.right() + ts, cy)
            else:
                tail.moveTo(body.left(), cy - tw / 2)
                tail.lineTo(body.left(), cy + tw / 2)
                tail.lineTo(body.left() - ts, cy)
        tail.closeSubpath()
        path.addPath(tail)

        p.setPen(QPen(self.BORDER_COLOR, 1))
        p.setBrush(self.BG_COLOR)
        p.drawPath(path)

    def _prepare_text(self, text: str):
        text = (text or "").strip()
        is_html = bool(re.search(r"</?\w+[^>]*>", text))

        # 先确定标签宽度
        if is_html:
            # 依据屏幕宽做一个更小的上限（比如 42%），同时别超过 _max_html_width
            scr_w = self._last_geo.width() if self._last_geo else 1200
            w_target = min(int(scr_w * 0.42), self._max_html_width)
            w_label = max(self._min_width, w_target)
        else:
            fm = QFontMetrics(self._label.font())
            ideal = fm.horizontalAdvance(text) + 16
            w_label = max(self._min_width, min(self._max_width, ideal))

        self._label.setFixedWidth(w_label)

        # HTML 直接一次性渲染，避免逐字把标签拆开
        if self._typing and not is_html:
            self._full_text = text
            self._type_idx = 0
            self._label.setText("")
            self._type_timer.start()
        else:
            self._label.setText(text)
            self._type_timer.stop()

        self.adjustSize()

    def _type_step(self):
        if self._type_idx >= len(self._full_text):
            self._type_timer.stop()
            return
        step = max(1, len(self._full_text) // 140)
        self._type_idx += step
        self._label.setText(self._full_text[: self._type_idx])
        self.adjustSize()

    def _size_hint_for(self, text: str) -> QtCore.QSize:
        if text == "":
            text = " " * 4
        is_html = bool(re.search(r"</?\w+[^>]*>", text))
        if is_html:
            doc = QTextDocument()
            doc.setHtml(text)
            doc.setTextWidth(self._label.width())
            brw, brh = int(doc.size().width()), int(doc.size().height())
        else:
            fm = QFontMetrics(self._label.font())
            br = fm.boundingRect(0, 0, self._label.width(), 10_000, Qt.TextWordWrap, text)
            brw, brh = br.width(), br.height()

        w = max(self._label.width(), brw) + 28
        h = brh + 24 + self._tail_size
        if self._last_geo:
            w = min(w, int(self._last_geo.width() * 0.60))  # 仅用于兜底，HTML 之前已被收窄
        return QtCore.QSize(w, h)

    def sizeHint(self) -> QtCore.QSize:
        return self._size_hint_for(self._label.text())

    def _suggest_geometry(
        self, anchor_rect: QtCore.QRect, hint_size: QtCore.QSize, prefer: str
    ) -> QtCore.QRect:
        screen = (
            QGuiApplication.screenAt(anchor_rect.center())
            or (self.windowHandle().screen() if self.windowHandle() else None)
            or QGuiApplication.primaryScreen()
        )
        geo = screen.availableGeometry()

        w, h = hint_size.width(), hint_size.height()
        candidates = {
            "right": QtCore.QRect(
                anchor_rect.right() + 12, anchor_rect.center().y() - h // 2, w, h
            ),
            "left": QtCore.QRect(
                anchor_rect.left() - w - 12, anchor_rect.center().y() - h // 2, w, h
            ),
            "above": QtCore.QRect(
                anchor_rect.center().x() - w // 2, anchor_rect.top() - h - 12, w, h
            ),
            "below": QtCore.QRect(
                anchor_rect.center().x() - w // 2, anchor_rect.bottom() + 12, w, h
            ),
        }
        order = [prefer] + [
            k for k in ("right", "left", "above", "below") if k != prefer
        ]
        pad = 12
        for k in order:
            r = candidates[k]
            x = max(geo.left() + pad, min(r.x(), geo.right() - w - pad))
            y = max(geo.top() + pad, min(r.y(), geo.bottom() - h - pad))
            r = QtCore.QRect(x, y, w, h).intersected(geo.adjusted(4, 4, -4, -4))
            if r.width() > 16 and r.height() > 16:
                self._tail_side = {
                    "right": "left",
                    "left": "right",
                    "above": "bottom",
                    "below": "top",
                }[k]
                return r

        self._tail_side = "bottom"
        r = QtCore.QRect(geo.center().x() - w // 2, geo.center().y() - h // 2, w, h)
        return r.intersected(geo.adjusted(4, 4, -4, -4))


# -------- Input Bar --------
class InputBar(QtWidgets.QWidget):
    sigSubmit = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(
            parent,
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.NoDropShadowWindowHint,
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(QtCore.Qt.WindowDoesNotAcceptFocus, False)
        self.setWindowTitle("像素香蕉 · 输入")

        self.back = QtWidgets.QFrame(self)
        self.back.setStyleSheet(
            """
            QFrame { background: rgba(25,25,25,190); border-radius: 12px; }
            QLineEdit { border: none; padding: 10px 12px; color: #f2f2f2; background: transparent; font-size: 14px; }
            QPushButton { background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.18);
                          border-radius:10px; padding:8px 12px; color:#f2f2f2; }
            QPushButton:hover { background: rgba(255,255,255,0.18); }
        """
        )
        lay = QtWidgets.QHBoxLayout(self.back)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
        self.edit = QtWidgets.QLineEdit(self.back)
        self.edit.setPlaceholderText("和香蕉聊点什么…（Enter 发送，Esc 关闭）")
        self.btn = QtWidgets.QPushButton("发送", self.back)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.btn, 0)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.back)

        self.btn.clicked.connect(self._submit)
        self.edit.returnPressed.connect(self._submit)

        self._fade = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160)
        self.setWindowOpacity(0.0)
        self._fade_conn_hide = False

        if sys.platform.startswith("win"):
            self.setGraphicsEffect(None)

    def _disconnect_fade_finished(self):
        if self._fade_conn_hide:
            try:
                self._fade.finished.disconnect(self.hide)
            except (TypeError, RuntimeError):
                pass
            self._fade_conn_hide = False

    def keyPressEvent(self, e: QtGui.QKeyEvent):
        if e.key() == QtCore.Qt.Key_Escape:
            self.hide_with_fade()
            e.accept()
            return
        super().keyPressEvent(e)

    def show_at_bottom(self):
        if self.isVisible():
            self.raise_()
            try:
                self.activateWindow()
            except Exception:
                pass
            self.edit.setFocus()
            self.edit.selectAll()
            return

        scr_obj = (
            QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
            or (
                self.parent().windowHandle().screen()
                if self.parent() and self.parent().windowHandle()
                else None
            )
            or QtGui.QGuiApplication.primaryScreen()
        )
        geo = scr_obj.availableGeometry()

        w, h = 520, 48
        x = geo.center().x() - w // 2
        y = geo.bottom() - h - 24

        pad = 12
        x = max(geo.left() + pad, min(x, geo.right() - w - pad))
        y = max(geo.top() + pad, min(y, geo.bottom() - h - pad))

        rect = QtCore.QRect(int(x), int(y), int(w), int(h)).intersected(
            geo.adjusted(4, 4, -4, -4)
        )

        self.setGeometry(rect)
        self.back.setGeometry(0, 0, rect.width(), rect.height())

        self._disconnect_fade_finished()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._fade.start()
        self.edit.setFocus()
        self.edit.selectAll()

    def hide_with_fade(self):
        if not self.isVisible():
            return
        self._disconnect_fade_finished()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QtCore.QEasingCurve.InCubic)
        if not self._fade_conn_hide:
            self._fade.finished.connect(self.hide)
            self._fade_conn_hide = True
        self._fade.start()

    def _submit(self):
        text = self.edit.text().strip()
        if not text:
            return
        self.edit.clear()
        self.hide_with_fade()
        self.sigSubmit.emit(text)


# -------- Sprite --------
# widgets.py —— 替换整个 BananaSprite 类
class BananaSprite(QtWidgets.QWidget):
    clicked = QtCore.Signal()

    def __init__(self, scale: int = 6, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.scale = max(3, int(scale))
        # 保持与像素版同尺寸：22x16 单位 * scale
        self.base_w, self.base_h = 11, 8
        self.setFixedSize(self.base_w * self.scale, self.base_h * self.scale)
        self._press_pos = None
        self._press_local = None
        self._press_ms = 0.0

    def _norm_rect(self) -> QtCore.QRectF:
        # 留一点边距，避免贴边被裁
        margin = max(1, self.scale // 3)
        return QtCore.QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)

    def paintEvent(self, e: QtGui.QPaintEvent):  # noqa
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)

        r = self._norm_rect()
        X = lambda x: r.left() + r.width() * (x / 100.0)
        Y = lambda y: r.top()  + r.height() * (y / 100.0)

        # 轻微投影（柔和体积感）
        shadow = QtGui.QPainterPath()
        shadow.moveTo(X(12), Y(64))
        shadow.cubicTo(X(18), Y(42), X(52), Y(34), X(86), Y(50))
        shadow.cubicTo(X(70), Y(78), X(40), Y(96), X(18), Y(94))
        p.fillPath(shadow, QtGui.QColor(0, 0, 0, 40))

        # 主体：两段三次贝塞尔，形状与托盘图标一致
        path = QtGui.QPainterPath()
        path.moveTo(X(12), Y(62))
        path.cubicTo(X(15), Y(36), X(52), Y(24), X(86), Y(40))
        path.cubicTo(X(70), Y(70), X(42), Y(88), X(20), Y(86))
        path.cubicTo(X(12), Y(80), X(10), Y(70), X(12), Y(62))

        grad = QtGui.QLinearGradient(X(20), Y(40), X(80), Y(86))
        grad.setColorAt(0.00, QtGui.QColor(255, 236, 110))  # 高光黄
        grad.setColorAt(0.60, QtGui.QColor(250, 208,  60))  # 主体黄
        grad.setColorAt(1.00, QtGui.QColor(225, 178,  40))  # 暗部黄
        p.fillPath(path, grad)

        pen = QtGui.QPen(QtGui.QColor(155, 115, 30))
        pen.setWidthF(max(1.0, self.scale / 6.0))
        p.setPen(pen)
        p.drawPath(path)

        # 侧边高光
        hpath = QtGui.QPainterPath()
        hpath.moveTo(X(28), Y(56))
        hpath.cubicTo(X(38), Y(38), X(58), Y(34), X(76), Y(46))
        hpen = QtGui.QPen(QtGui.QColor(255, 255, 245, 160))
        hpen.setWidthF(max(1.0, self.scale / 7.0))
        p.setPen(hpen)
        p.drawPath(hpath)

        # 果柄（蒂）
        stalk = QtGui.QPainterPath()
        stalk.addRoundedRect(QtCore.QRectF(X(82), Y(36), r.width() * 0.08, r.height() * 0.10),
                             max(1.0, self.scale / 4.5), max(1.0, self.scale / 4.5))
        p.fillPath(stalk, QtGui.QColor(90, 60, 40))
        p.setPen(QtGui.QPen(QtGui.QColor(70, 45, 30)))
        p.drawPath(stalk)

    # —— 保持原有“点击触发输入、拖拽移动、右键菜单”的手感 —— #
    def mousePressEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button() == QtCore.Qt.LeftButton:
            self._press_pos = e.globalPosition().toPoint()
            self._press_local = e.position().toPoint()
            self._press_ms = time.time()
            e.accept()
        elif e.button() == QtCore.Qt.RightButton:
            if self.parent():
                self.parent().customContextMenuRequested.emit(e.globalPosition().toPoint())
            e.accept()
        else:
            e.ignore()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.buttons() & QtCore.Qt.LeftButton and self._press_pos is not None and self.parent():
            gp = e.globalPosition().toPoint()
            diff = gp - self._press_pos
            if diff.manhattanLength() >= 3:
                self.parent().move(self.parent().pos() + diff)
                self._press_pos = gp

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button() == QtCore.Qt.LeftButton:
            moved = (e.position().toPoint() - (self._press_local or e.position().toPoint())).manhattanLength()
            dur = (time.time() - self._press_ms) if self._press_ms else 0
            if moved < 3 and dur < 0.4:
                self.clicked.emit()
            self._press_pos = None
            e.accept()
        else:
            e.ignore()

