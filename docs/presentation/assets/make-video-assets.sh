#!/usr/bin/env bash
# 시연영상에 넣을 그림을 다시 뽑는다. video-assets.html을 고친 뒤 이 폴더에서:  bash make-video-assets.sh
# 모두 1920x1080 PNG다. 자막(video-cap-*)과 video-s8-numbers-overlay.png는 바탕이 투명하다.
set -euo pipefail
cd "$(dirname "$0")"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

shot() {  # 조각 주소, 파일 이름, 바탕색(RRGGBBAA. 투명은 00000000)
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --window-size=1920,1080 --default-background-color="$3" \
    --screenshot="$PWD/$2" "file://$PWD/video-assets.html#$1" >/dev/null 2>&1
  echo "뽑음: $2"
}

shot s1            video-s1-compare.png          ffffffff
shot s8            video-s8-numbers.png          ffffffff
shot s8-over       video-s8-numbers-overlay.png  00000000
shot cap-worker    video-cap-worker.png          00000000
shot cap-manager   video-cap-manager.png         00000000
shot cap-insight2  video-cap-insight2.png        00000000
shot cap-insight3  video-cap-insight3.png        00000000
shot cap-4x        video-cap-4x.png              00000000
shot cap-refresh   video-cap-refresh.png         00000000
shot cap-demo-data video-cap-demo-data.png       00000000
shot cap-preview   video-cap-preview.png         ffffffff
