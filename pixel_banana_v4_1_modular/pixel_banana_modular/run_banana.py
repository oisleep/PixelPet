
# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# from __future__ import annotations
# from PySide6 import QtCore, QtWidgets, QtGui
# from banana.app import PetWindow

# def main():
#     try:
#         QtCore.QCoreApplication.setHighDpiScaleFactorRoundingPolicy(
#             QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
#         )
#     except Exception:
#         pass
#     app = QtWidgets.QApplication([])
#     w = PetWindow(app)
#     # 启动时居中显示（主屏）
#     scr = QtGui.QGuiApplication.primaryScreen().availableGeometry()
#     w.move(scr.center().x() - w.width()//2, scr.center().y() - w.height()//2)
#     w.show()
#     app.exec()

# if __name__ == "__main__":
#     main()

#!/usr/bin/env python3
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

    # —— 一键自检 / 唤起 Ollama / 触发拉模型 —— #
    ok = False
    try:
        # 需要你已在 LocalModelClient 里添加 ensure_ready() 方法
        ok = bool(getattr(w.client, "ensure_ready", lambda: False)())
    except Exception:
        ok = False

    if not ok:
        QtWidgets.QMessageBox.information(
            w, "启动检查",
            "未检测到 Ollama 服务，我已尝试为你启动。\n"
            "若未安装，请先安装 Ollama（ollama.com）然后重新打开香蕉。",
        )
    else:
        # 可选的小提示：如果还没真正拉到目标模型，告知“后台准备中”
        try:
            import requests
            base = w.client.base_url.rstrip("/")
            name = w.client.model_name
            base_name = name.split(":")[0]
            tags = requests.get(f"{base}/api/tags", timeout=5).json().get("models", [])
            have = any(base_name in (m.get("name") or "") for m in tags)
            if not have:
                QtWidgets.QMessageBox.information(
                    w, "准备模型",
                    f"正在后台准备模型：{name}\n"
                    "首次下载会花点时间，准备好后就可以开始聊天啦～"
                )
        except Exception:
            pass

    # 启动时居中显示（主屏）
    scr = QtGui.QGuiApplication.primaryScreen().availableGeometry()
    w.move(scr.center().x() - w.width() // 2, scr.center().y() - w.height() // 2)
    w.show()
    app.exec()

if __name__ == "__main__":
    main()


# pyinstaller --noconfirm --windowed --name "Banana" --collect-all PySide6 --collect-submodules PySide6 pixel_banana/run_banana.py