#!/usr/bin/env bash
# 无需本机 Windows：用 Docker + Wine 容器（cdrx/pyinstaller-windows）构建 Windows exe
# 在任意装有 Docker 的 Linux/macOS 上运行：  bash build_exe_docker.sh
set -euo pipefail

cd "$(dirname "$0")"

# 镜像内置 Python 3.11 + PyInstaller，并通过 Wine 产出 Windows 可执行文件
IMAGE="cdrx/pyinstaller-windows:latest"

echo "==> 拉取构建镜像（首次较慢）"
docker pull "$IMAGE"

echo "==> 构建 Windows exe（使用项目自带 DiskCC.spec，输出 dist/DiskCC.exe）"
docker run --rm \
  -v "$(pwd):/app" \
  -w /app \
  "$IMAGE" \
  pyinstaller --noconfirm --clean DiskCC.spec

echo "==> 完成：dist/DiskCC.exe"
ls -lh dist/DiskCC.exe 2>/dev/null || echo "（未生成，请检查上方日志）"

# 说明：
# 1) 该镜像用 Wine 运行 Windows 版 Python/PyInstaller，因此打出的就是真·Windows exe。
# 2) PySide6 的 Qt 插件偶尔收集不全，如启动报 "could not find Qt platform plugin"，
#    可在镜像内执行：
#      docker run --rm -it -v "$(pwd):/app" -w /app "$IMAGE" bash
#    然后手动：pyinstaller ... --collect-submodules PySide6 再构建。
# 3) 想单文件可把 --onedir 换成 --onefile（启动慢一点）。
