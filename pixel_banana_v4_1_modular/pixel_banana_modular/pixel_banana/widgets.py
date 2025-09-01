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


# -------- Icon --------
def banana_pixmap(size: int = 32) -> QtGui.QPixmap:
    w, h = 22, 16
    s = max(1, min(size // w, size // h))
    img_w, img_h = w * s, h * s
    ox, oy = (size - img_w) // 2, (size - img_h) // 2

    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, False)

    body = [
        "......................",
        "......1111111.........",
        "....11111111111....3..",
        "...1111111111111..3...",
        "..111111111111111.....",
        "..1111111111111111....",
        "..1111111111111111....",
        "...111111111111111....",
        "....11111111111111....",
        ".....111111111111.....",
        "......1111111111..2...",
        "........1111111..22...",
        "..........111.....2...",
        "............1.........",
        "......................",
        "......................",
    ]
    c_body, c_shadow = QtGui.QColor(250, 208, 60), QtGui.QColor(210, 170, 50)
    c_stalk, c_high = QtGui.QColor(90, 60, 40), QtGui.QColor(255, 255, 240)

    points = []
    for y, row in enumerate(body):
        for x, ch in enumerate(row):
            if ch == "1":
                points.append((x, y, 1))
    shadow = [
        (x, y)
        for y, row in enumerate(body)
        for x, ch in enumerate(row)
        if ch == "1" and (y >= 9 or x >= 12)
    ]
    for x, y in shadow:
        points.append((x, y + 1 if y + 1 < h else y, 2))
    points += [(18, 2, 3), (19, 2, 3), (7, 4, 4), (8, 5, 4), (6, 6, 4)]

    for x, y, val in points:
        color = (
            c_body
            if val == 1
            else c_shadow if val == 2 else c_stalk if val == 3 else c_high
        )
        p.fillRect(ox + x * s, oy + y * s, s, s, color)

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
        self._pop.start()
        if self._auto_close_ms > 0:
            self._close_timer.start(self._auto_close_ms)

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
        fm = QFontMetrics(self._label.font())
        ideal = fm.horizontalAdvance(text) + 16
        w_label = max(self._min_width, min(self._max_width, ideal))
        self._label.setFixedWidth(w_label)
        if self._typing:
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
        fm = QFontMetrics(self._label.font())
        br = fm.boundingRect(0, 0, self._label.width(), 10_000, Qt.TextWordWrap, text)
        w = max(self._label.width(), br.width()) + 28
        h = br.height() + 24 + self._tail_size
        if self._last_geo:
            w = min(w, int(self._last_geo.width() * 0.60))
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

        if sys.platform.startswith("win"):
            self.setGraphicsEffect(None)

    def _disconnect_fade_finished(self):
        try:
            self._fade.finished.disconnect(self.hide)
        except Exception:
            pass

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
        self._fade.finished.connect(self.hide)
        self._fade.start()

    def _submit(self):
        text = self.edit.text().strip()
        if not text:
            return
        self.edit.clear()
        self.hide_with_fade()
        self.sigSubmit.emit(text)


# -------- Sprite --------
class BananaSprite(QtWidgets.QWidget):
    clicked = QtCore.Signal()

    def __init__(self, scale: int = 6, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.scale = max(3, scale)
        self.maturity = 1  # 固定为“正好”
        self.grid = self._make_grid()
        self.setFixedSize(self.grid.width * self.scale, self.grid.height * self.scale)

    class Grid:
        def __init__(self, w, h, points):
            self.width, self.height, self.points = w, h, points

    def _make_grid(self) -> "BananaSprite.Grid":
        w, h = 22, 16
        pts = set()
        body = [
            "......................",
            "......1111111.........",
            "....11111111111....3..",
            "...1111111111111..3...",
            "..111111111111111.....",
            "..1111111111111111....",
            "..1111111111111111....",
            "...111111111111111....",
            "....11111111111111....",
            ".....111111111111.....",
            "......1111111111..2...",
            "........1111111..22...",
            "..........111.....2...",
            "............1.........",
            "......................",
            "......................",
        ]
        shadow = [
            (x, y)
            for y, row in enumerate(body)
            for x, ch in enumerate(row)
            if ch == "1" and (y >= 9 or x >= 12)
        ]
        for y, row in enumerate(body):
            for x, ch in enumerate(row):
                if ch == "1":
                    pts.add((x, y, 1))
        for x, y in shadow:
            pts.add((x, y + 1 if y + 1 < h else y, 2))
        pts.add((18, 2, 3))
        pts.add((19, 2, 3))
        for x, y in ((7, 4), (8, 5), (6, 6)):
            pts.add((x, y, 4))
        return BananaSprite.Grid(w, h, sorted(list(pts)))

    def paintEvent(self, e: QtGui.QPaintEvent):  # noqa
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)
        c_body, c_shadow = QtGui.QColor(250, 208, 60), QtGui.QColor(210, 170, 50)
        c_stalk, c_high = QtGui.QColor(90, 60, 40), QtGui.QColor(255, 255, 240)
        for x, y, val in self.grid.points:
            color = (
                c_body
                if val == 1
                else (
                    c_shadow
                    if val == 2
                    else (
                        c_stalk
                        if val == 3
                        else c_high if val == 4 else QtGui.QColor(0, 0, 0, 0)
                    )
                )
            )
            p.fillRect(x * self.scale, y * self.scale, self.scale, self.scale, color)

    def mousePressEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button() == QtCore.Qt.LeftButton:
            self._press_pos = e.globalPosition().toPoint()
            self._press_local = e.position().toPoint()
            self._press_ms = time.time()
            e.accept()
        elif e.button() == QtCore.Qt.RightButton:
            self.parent().customContextMenuRequested.emit(e.globalPosition().toPoint())
            e.accept()
        else:
            e.ignore()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.buttons() & QtCore.Qt.LeftButton:
            gp = e.globalPosition().toPoint()
            diff = gp - self._press_pos
            if diff.manhattanLength() >= 3:
                self.parent().move(self.parent().pos() + diff)
                self._press_pos = gp

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):  # noqa
        if e.button() == QtCore.Qt.LeftButton:
            moved = (e.position().toPoint() - self._press_local).manhattanLength() > 3
            dt = time.time() - getattr(self, "_press_ms", time.time())
            if not moved and dt < 0.3:
                self.clicked.emit()
