"""启动免责声明弹窗：提醒用户谨慎清理、做好备份。"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

from ..config import Config

_DISCLAIMER_TEXT = (
    "欢迎使用 DiskCC！\n\n"
    "在开始使用前，请务必了解：\n\n"
    "1. 清理操作会删除文件或文件夹，请逐项仔细查看待清理内容，"
    "确认无误后再执行清理；\n"
    "2. 为防止误删，扫描结果默认不勾选任何项目，请自行甄别后手动勾选；\n"
    "3. 清理前请做好重要数据备份（本工具默认优先移入回收站，"
    "并可在设置中开启备份清单，但回收站可能被清空，备份清单不等于备份文件本身）；\n"
    "4. 因使用本工具造成的任何数据丢失或损失，作者不承担任何责任。\n\n"
    "请确认您已理解上述内容。"
)


def show_disclaimer(parent: QWidget | None, cfg: Config) -> bool:
    """显示免责声明。返回 True 表示用户点击了确认。

    勾选"不再提示"并确认后，写入配置，后续启动不再显示。
    """
    box = QMessageBox(parent)
    box.setWindowTitle("使用须知与免责声明")
    box.setIcon(QMessageBox.Warning)
    box.setText(_DISCLAIMER_TEXT)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setDefaultButton(QMessageBox.StandardButton.Ok)

    checkbox = QCheckBox("不再提示")
    box.setCheckBox(checkbox)

    box.exec()

    accepted = box.result() == QMessageBox.StandardButton.Ok
    if accepted and checkbox.isChecked():
        cfg.set("show_disclaimer", False)
        try:
            cfg.save()
        except Exception:
            pass
    return accepted
