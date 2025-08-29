
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6 import QtCore, QtWidgets, QtGui
from pixel_banana.app import PetWindow

def main():
    try:
        QtCore.QCoreApplication.setHighDpiScaleFactorRoundingPolicy(
            QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass
    app = QtWidgets.QApplication([])
    w = PetWindow(app)
    # 启动时居中显示（主屏）
    scr = QtGui.QGuiApplication.primaryScreen().availableGeometry()
    w.move(scr.center().x() - w.width()//2, scr.center().y() - w.height()//2)
    w.show()
    app.exec()

if __name__ == "__main__":
    main()
