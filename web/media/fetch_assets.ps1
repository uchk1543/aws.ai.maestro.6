# 영상·Blender 큰 파일을 GitHub Release에서 받아 web/media 제자리에 푼다 (Windows PowerShell)
# 쓰는 법 (저장소 어디서든):  powershell -File web/media/fetch_assets.ps1 [묶음 ...]
#   묶음: blender-scenes, video-media, tripo-originals, final-renders  (없으면 blender-scenes, video-media)
# 필요: gh CLI 로그인 (gh auth login)
param([string[]]$Groups = @("blender-scenes", "video-media"))
$ErrorActionPreference = "Stop"
$Tag = "media-assets-2026-11-21"
$Repo = "uchk1543/aws.ai.maestro.6"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path   # 저장소 루트 (zip 안의 경로가 web/media/... 로 시작한다)
$Dl = Join-Path $PSScriptRoot "_downloads"
New-Item -ItemType Directory -Force $Dl | Out-Null
foreach ($g in $Groups) {
    Write-Host "[fetch] $g.zip 받는 중"
    gh release download $Tag --repo $Repo --pattern "$g.zip" --dir $Dl --clobber
    if ($LASTEXITCODE -ne 0) { throw "$g.zip 를 받지 못했습니다" }
    Write-Host "[fetch] $g.zip 푸는 중"
    Expand-Archive -Path (Join-Path $Dl "$g.zip") -DestinationPath $Root -Force
}
Write-Host "[fetch] 끝. 받은 zip 은 $Dl 에 있다 (지워도 된다)"
