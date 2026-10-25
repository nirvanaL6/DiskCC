#!/usr/bin/env bash
# 自建 Wine 镜像构建 Windows exe（无需本机 Windows）
# 用法：  bash build_exe_wine.sh
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="diskcc-build:wine"

echo "==> [1/2] 构建镜像（含 Wine + Python3.11 + PySide6，首次较慢，可能 10~30 分钟）"
docker build -t "$IMAGE" -f Dockerfile.wine .

echo "==> [2/2] 运行 PyInstaller 打包（使用项目自带 DiskCC.spec）"
docker run --rm -v "$(pwd):/src" -w /src "$IMAGE" bash -c "
    wine64 c:/Python311/python.exe -m PyInstaller --noconfirm --clean DiskCC.spec
"

echo "==> 完成：dist/DiskCC.exe"
ls -lh dist/DiskCC.exe 2>/dev/null || echo "（未生成，请检查上方日志）"
