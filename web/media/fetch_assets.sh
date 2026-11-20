#!/usr/bin/env bash
# 영상·Blender 큰 파일을 GitHub Release에서 받아 web/media 제자리에 푼다 (bash / Git Bash)
# 쓰는 법 (저장소 어디서든):  bash web/media/fetch_assets.sh [묶음 ...]
#   묶음: blender-scenes, video-media, tripo-originals, final-renders  (없으면 blender-scenes, video-media)
# 필요: gh CLI 로그인 (gh auth login), unzip
set -euo pipefail
TAG="media-assets-2026-11-21"
REPO="uchk1543/aws.ai.maestro.6"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"   # 저장소 루트 (zip 안의 경로가 web/media/... 로 시작한다)
DL="$HERE/_downloads"
mkdir -p "$DL"
[ $# -eq 0 ] && set -- blender-scenes video-media
for g in "$@"; do
  echo "[fetch] $g.zip 받는 중"
  gh release download "$TAG" --repo "$REPO" --pattern "$g.zip" --dir "$DL" --clobber
  echo "[fetch] $g.zip 푸는 중"
  unzip -o -q "$DL/$g.zip" -d "$ROOT"
done
echo "[fetch] 끝. 받은 zip 은 $DL 에 있다 (지워도 된다)"
