# Install (or update) HOLO, the free webcam hand-gesture notes app from the reference video's creator.
#   Source: https://github.com/zubair-trabzada/holo-gestures  (MIT license, Python standard library + Chrome)
# Run from the JARVIS folder:   powershell -ExecutionPolicy Bypass -File scripts\setup_holo.ps1
# Then say "Jarvis, open HOLO" (or click HOLO > Open HOLO in the Brain).
$ErrorActionPreference = 'Stop'
$target = Join-Path $HOME 'holo'
$repo = 'https://github.com/zubair-trabzada/holo-gestures.git'

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host 'Git is not installed. Install it with:  winget install --id Git.Git -e' -ForegroundColor Yellow
    Write-Host "Or download the ZIP from $($repo -replace '\.git$','') (Code > Download ZIP) and extract it to $target"
    exit 1
}
if (Test-Path (Join-Path $target 'server.py')) {
    Write-Host "Updating HOLO in $target ..."
    git -C $target pull --ff-only
} elseif (Test-Path $target) {
    Write-Host "$target exists but isn't HOLO. Move it aside or set HOLO_DIR in .env to another folder." -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "Cloning HOLO into $target ..."
    git clone --depth 1 $repo $target
}

# Point HOLO at the JARVIS knowledge vault (the original holo.json is kept as holo.json.bak).
$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
& $python -c "import sys; sys.path.insert(0, r'$PSScriptRoot\..'); import holo_bridge, pathlib; print('HOLO', holo_bridge.configure(pathlib.Path(r'$target')))"

Write-Host ''
Write-Host 'HOLO is ready.' -ForegroundColor Green
Write-Host '  * Say "Jarvis, open HOLO", or run:  cd ~\holo; python server.py   then open http://localhost:4890 in Chrome'
Write-Host '  * Allow the camera, raise a hand. Pinch = grab, quick pinch = open, two-hand stretch = read, squeeze = JARVIS summary.'
Write-Host '  * Press J inside HOLO for its own narration, F for extra effects. Add ?sim=1 to the URL for a demo without a camera.'
