# -*- mode: python ; coding: utf-8 -*-
"""DiskCC 打包配置（PyInstaller）。

用法：pyinstaller DiskCC.spec     产出单文件 dist/DiskCC(.exe)

v1.2.0 说明：
1. 体积：排除大量用不到的 Qt 模块（WebEngine / QML / 3D / 多媒体 / 图表 …），
   这是 PySide6 单文件程序最主要的体积来源；再叠加 optimize=2 与 strip。
2. 杀软误报：显式禁用 UPX 压缩（UPX 加壳是各家杀软的重点怀疑对象），
   并写入版本资源（公司名称/产品名/版本号），显著降低"未知程序"评分。
"""

import os
import sys

IS_WIN = sys.platform.startswith("win")

# ---------------------------------------------------------------- 体积裁剪
# 说明：DiskCC 只用 QtWidgets / QtCore / QtGui。下面这些模块确定不会被引用，
# 但会被 PyInstaller 一并打进来（其中 QtWebEngine* 单个就有上百 MB）。
QT_EXCLUDES = [
    # Web 引擎（体积大户）
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    # QML / Quick
    "PySide6.QtQml", "PySide6.QtQmlModels", "PySide6.QtQmlWorkerScript",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets", "PySide6.QtQuickTest",
    # 3D / 图表 / 数据可视化
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    # 多媒体 / 设备 / 定位
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtPositioningQuick", "PySide6.QtBluetooth", "PySide6.QtSerialPort",
    "PySide6.QtSensors",
    # 开发/测试/文档类
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools",
    # 其它用不到的后端
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtPrintSupport", "PySide6.QtSql", "PySide6.QtNetworkAuth",
    "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtHttpServer",
]

# 非 Qt 的无关依赖（注意：不能排除 ssl / urllib / http，AI 联网要用）
PY_EXCLUDES = [
    "tkinter", "unittest", "pydoc", "doctest", "pytest",
    "numpy", "PIL", "matplotlib", "pandas", "scipy", "IPython", "notebook",
    "sqlite3", "curses", "setuptools", "pip",
]

# Windows 平台专属（AxContainer 只在 Windows 轮子里有）
if IS_WIN:
    QT_EXCLUDES.append("PySide6.QtAxContainer")

excludes = QT_EXCLUDES + PY_EXCLUDES + ["tests"]   # tests 包仅开发用，不进 exe

# v1.3.2：assets/logo.png（约 1.4MB）实际上没有任何代码使用——
# app_icon_path() 优先用 diskcc.ico，png 只作为 ico 缺失时的兜底，
# 而 ico 一定会被打包。把它排除出单文件产物可直接省下这部分体积。
# SPECPATH 由 PyInstaller 注入；直接 exec 本 spec 的测试环境回退为 cwd
SPECPATH = globals().get("SPECPATH", os.getcwd())
ALL_ASSETS = os.path.join(SPECPATH, "assets")
datas = [
    (os.path.join(ALL_ASSETS, "diskcc.ico"), "assets"),
    (os.path.join(SPECPATH, "README.md"), "."),
]

# ------------------------------------------------------------ 体积瘦身
# PySide6 的 hook 会把整个 Qt 目录收集进来：即使在 excludes 里排除了对应的
# Python 模块，原生库、QML 资源、翻译文件与类型元数据仍会进产物。实测
# PySide6_Essentials 轮子内这些"用不上但会被打包"的内容合计约 75MB：
#   qml/ 20MB、translations/ 13MB、resources(icudtl) 11MB、QtOpenGL.pyd 8.8MB、
#   Qt6Quick 6MB、Qt6Qml 5.1MB、Qt6Designer 5.1MB、metatypes 5.9MB ...
# v1.3.4 起默认剔除其中确定不会被加载的部分（保留 icudtl.dat：Qt6 的文本处理
# 依赖 ICU 数据，误删会导致启动失败）。
# 如需排查"是不是裁过头了"，用 DISKCC_SLIM=0 关闭后对照构建即可。
SLIM = os.environ.get("DISKCC_SLIM", "1") != "0"

# 匹配时同时看源路径与包内目标路径（a.binaries / a.datas 的第 1、2 个元素）。
QT_BLOAT_PATTERNS = (
    # 资源与元数据：运行时不会加载
    "/qml/", "\\qml\\", "/translations/", "\\translations\\",
    "/metatypes/", "\\metatypes\\",
    # QML / Quick / Designer 的原生库与命令行工具
    "qt6qml", "qt6quick", "qtquick", "qt6designer", "qt6qmlcompiler",
    "libqt6qml", "libqt6quick", "libqt6designer",
    "qmltooling", "qmlls", "qmlformat", "qtvirtualkeyboard",
    # 已在 excludes 中排除、但 hook 仍会收进来的绑定与库
    "qtopengl", "qt6pdf", "qtwayland", "libqt6eglfs",
    # 用不到的插件后端
    "sqldrivers", "platforminputcontexts", "networkinformation",
    "/designer/", "\\designer\\",
    # 平台插件只需 qwindows（qdirect2d / qminimal 用不到）
    "qdirect2d", "qminimal",
    # 图片格式只需 ico/jpeg/gif/svg（图标与界面用），其余可省
    "qwebp", "qicns", "qtiff", "qpdf",
)


def _is_bloat(toc_entry) -> bool:
    name = ((toc_entry[0] or "") + " " + (toc_entry[1] or "")).lower()
    return any(p in name for p in QT_BLOAT_PATTERNS)


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=2,          # 去掉断言与文档字符串，略微减小并加快启动
)

pyz = PYZ(a.pure)

if SLIM:
    # 关键：v1.3.2 只过滤了 a.binaries，而 qml/translations/metatypes 属于
    # a.datas，因此从未被裁掉——这正是"每次更新都变大"的一部分原因。
    a.binaries = [b for b in a.binaries if not _is_bloat(b)]
    a.datas = [d for d in a.datas if not _is_bloat(d)]

# 重要：EXE() 的前 5 个 TOC 参数（pyz / a.scripts / a.binaries / a.datas / []）
# 必须按【位置参数】传入。PyInstaller 的 EXE(*args, **kwargs) 只按位置接收这些
# TOC，其余关键字用于选项；若误写成 a_binaries= 等关键字会被静默忽略，导致
# python313.dll 等二进制依赖完全没打进 exe，运行时报"找不到指定的模块"。
exe_kwargs = dict(
    name="DiskCC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,         # Windows 上 strip PE 可能损坏 DLL/exe，导致加载器弹窗挂死；关闭
    upx=False,           # 不用 UPX 加壳：UPX 加壳是各家杀软的重点怀疑对象
    runtime_tmpdir=None,
    console=False,       # GUI 程序，不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if IS_WIN:
    exe_kwargs["icon"] = os.path.join(SPECPATH, "assets", "diskcc.ico")
    # 默认 requireAdministrator：清理 %WINDIR%\Temp、SoftwareDistribution、
    # 执行 DISM / powercfg 等都必须管理员权限，启动时直接提权最省事。
    # （v1.3.3 曾改为 asInvoker 排查 CI 挂死，后证实真凶是 strip 而非 UAC，
    #   v1.3.4 恢复为默认提权。）
    # 需要不提权的产物（例如 CI 冒烟）时用 DISKCC_UAC=0 构建。
    exe_kwargs["uac_admin"] = os.environ.get("DISKCC_UAC", "1") != "0"
    if os.path.isfile(os.path.join(SPECPATH, "file_version.txt")):
        exe_kwargs["version"] = os.path.join(SPECPATH, "file_version.txt")   # 版本资源

# v1.3.3：新增 onedir（目录模式）构建，DISKCC_ONEDIR=1 时启用。
# 背景：onefile 每次启动都要把 python3xx.dll 等全部解压到 %TEMP%\_MEIxxxx 再
# LoadLibrary，部分用户机器上这一步会被杀软实时扫描拦截，报
# "Failed to load Python DLL ... LoadLibrary: 内存位置访问无效"(错误 998)。
# onedir 不写临时目录、直接从程序目录加载，可从根上绕开该故障模式。
ONEDIR = os.environ.get("DISKCC_ONEDIR", "") == "1"

if ONEDIR:
    exe = EXE(
        pyz,
        a.scripts,
        [],                  # onedir：二进制由下方 COLLECT 输出到程序目录
        exclude_binaries=True,
        **exe_kwargs,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="DiskCC",       # 产物：dist/DiskCC/DiskCC.exe
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],                  # PyInstaller 6.x：Analysis 不再产 zipfiles，占位空 TOC
        **exe_kwargs,
    )
