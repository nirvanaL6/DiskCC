"""DiskCC 入口：GUI 模式 / 命令行模式 / 自测模式。"""

from __future__ import annotations

import argparse
import csv
import os
import sys


def _bootstrap_paths() -> None:
    """保证以源码方式运行时可以正确导入 diskcc 包。"""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def run_cli(args: argparse.Namespace) -> int:
    from diskcc.ai.analyzer import AIAnalyzer
    from diskcc.config import Config
    from diskcc.models import human_size
    from diskcc.scanner.manager import ScanManager

    cfg = Config.load(args.config)
    if args.min_size is not None:
        cfg.set("min_size_mb", args.min_size)
    ai = AIAnalyzer(cfg, lambda m: print(m, flush=True))
    manager = ScanManager(cfg, ai, log=lambda m: print(m, flush=True))
    result = manager.run()

    print("\n" + "=" * 72)
    print(f"扫描完成：{len(result.items)} 项，合计 {human_size(result.total_size)}，"
          f"耗时 {result.elapsed:.1f}s")
    print("=" * 72)
    by_cat = result.by_category()
    from diskcc.models import category_name

    for cat, items in sorted(by_cat.items(), key=lambda kv: -sum(i.size for i in kv[1])):
        size = sum(i.size for i in items)
        print(f"  {category_name(cat):<22} {len(items):>4} 项   {human_size(size):>12}")

    if args.out:
        ext = os.path.splitext(args.out)[1].lower()
        if ext == ".json":
            import json

            with open(args.out, "w", encoding="utf-8") as f:
                json.dump([i.to_dict() for i in result.items], f, ensure_ascii=False, indent=2)
        else:
            with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["名称", "大小(字节)", "风险", "分类", "归属软件", "来源", "说明", "路径"])
                for i in result.items:
                    w.writerow([i.name, i.size, i.risk.label, i.category_label,
                                i.software, i.source, i.reason, i.path])
        print(f"\n报告已导出：{args.out}")
    return 0


def run_gui() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from diskcc import resources
    from diskcc.ai.analyzer import AIAnalyzer
    from diskcc.config import Config
    from diskcc.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("DiskCC")
    _icon = resources.app_icon_path()
    if os.path.isfile(_icon):
        app.setWindowIcon(QIcon(_icon))
    cfg = Config.load()
    ai = AIAnalyzer(cfg)
    window = MainWindow(cfg, ai)
    window.update_ai_status()
    if cfg.get("show_disclaimer", True):
        from diskcc.ui.disclaimer import show_disclaimer
        show_disclaimer(window, cfg)   # 模态弹窗；勾选"不再提示"后写入配置
    window.show()
    return app.exec()


def main(argv=None) -> int:
    _bootstrap_paths()
    from diskcc import __version__
    parser = argparse.ArgumentParser(
        prog="DiskCC",
        description="Windows C 盘智能清理工具（内置规则库 + 可选 AI 识别）",
    )
    parser.add_argument("--cli", action="store_true", help="命令行模式：扫描并输出报告，不启动界面")
    parser.add_argument("--out", default="", help="命令行模式下导出报告的路径（.csv 或 .json）")
    parser.add_argument("--config", default="", help="指定配置文件路径")
    parser.add_argument("--min-size", type=float, default=None, help="忽略小于指定 MB 的项目")
    parser.add_argument("--selftest", action="store_true", help="运行内置自测（构造模拟磁盘树）")
    parser.add_argument("--admin", action="store_true", help="以管理员权限重新启动（Windows）")
    parser.add_argument("--version", action="version", version=f"DiskCC {__version__}",
                        help="显示版本号后退出（可用于验证 exe 能正常启动）")
    args = parser.parse_args(argv)

    if args.admin:
        from diskcc.utils import win

        if win.is_admin():
            print("当前已以管理员权限运行，无需再次提权。")
            return 0
        if win.relaunch_as_admin():
            return 0
        print("提权失败，请右键选择“以管理员身份运行”")
        return 1

    if args.selftest:
        from tests.selftest import main as selftest_main

        return selftest_main()

    if args.cli:
        return run_cli(args)

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
