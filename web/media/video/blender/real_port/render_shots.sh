#!/usr/bin/env bash
# 발표 영상에 쓰는 3D 네 구간만 렌더한다 (24fps 프레임 번호, 대시보드 장면과 같은 타임라인)
#   opening 1-150 입항 · unload 150-270 하역 · gate 300-470 검사·반출 · outro 470-650 항구 전체
set -e
cd "$(dirname "$0")"
B="/c/Program Files/Blender Foundation/Blender 4.0/blender.exe"
"$B" -b -P build_real.py > build.log 2>&1
for range in "1 150" "150 270" "300 470" "470 650"; do
  set -- $range
  "$B" -b real_port.blend -o "//frames/f####" -F PNG -s "$1" -e "$2" -a >> render.log 2>&1
done
echo done
