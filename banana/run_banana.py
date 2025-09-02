
# -*- coding: utf-8 -*-
from __future__ import annotations
from PySide6 import QtCore, QtWidgets, QtGui
from banana.app import PetWindow

def main():
    try:
        QtCore.QCoreApplication.setHighDpiScaleFactorRoundingPolicy(
            QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QtWidgets.QApplication([])

    # 先创建窗口（内部会创建 LocalModelClient）
    w = PetWindow(app)

    # ===== 首次运行：自检 / 唤起 Ollama / 拉取模型（带进度条） =====
    # 进度对话框（流式拉取时可视化）
    prog = QtWidgets.QProgressDialog("正在准备模型，请稍候…", "隐藏", 0, 100, w)
    prog.setWindowTitle("首次准备模型")
    prog.setWindowModality(QtCore.Qt.WindowModal)
    prog.setAutoClose(True)
    prog.setAutoReset(True)
    prog.setMinimumDuration(0)  # 立刻显示

    def on_progress(status, comp, total, pct):
        # ensure_ready(on_progress=...) 的回调：实时更新到进度条
        if pct is not None:
            prog.setValue(max(0, min(100, int(pct))))
        if status:
            prog.setLabelText(f"正在下载 {w.client.model_name}：{status}")
        QtWidgets.QApplication.processEvents()

    ok = False
    try:
        # 优先尝试带 on_progress 的调用；不支持则自动回退
        ensure_ready = getattr(w.client, "ensure_ready", None)
        if callable(ensure_ready):
            try:
                ok = bool(ensure_ready(on_progress=on_progress))
            except TypeError:
                # 老版本没有 on_progress 参数
                ok = bool(ensure_ready())
        else:
            ok = False
    except Exception:
        ok = False
    finally:
        prog.reset()

    if not ok:
        QtWidgets.QMessageBox.information(
            w, "启动检查",
            "未检测到 Ollama 服务，我已尝试为你启动。\n"
            "若未安装，请先安装 Ollama（ollama.com）然后重新打开香蕉。"
        )

    # ===== 启动时居中并显示 =====
    scr = QtGui.QGuiApplication.primaryScreen().availableGeometry()
    w.move(scr.center().x() - w.width() // 2, scr.center().y() - w.height() // 2)
    w.show()
    app.exec()

if __name__ == "__main__":
    main()


# pyinstaller --noconfirm --windowed --name "Banana" --collect-all PySide6 --collect-submodules PySide6 banana/run_banana.py