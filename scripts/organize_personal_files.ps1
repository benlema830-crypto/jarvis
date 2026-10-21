$ErrorActionPreference = 'Stop'
$desk = [Environment]::GetFolderPath('Desktop')
$docs = [Environment]::GetFolderPath('MyDocuments')
$downloads = 'C:\Users\Lemab\Downloads'
$repo = 'C:\Users\Lemab\jarvis'
$hub = 'C:\Users\Lemab\Documents\Jarvis Agent'
$auditPath = Join-Path $repo 'data\personal-organization-log.json'
$moves = [System.Collections.Generic.List[object]]::new()
if (Test-Path -LiteralPath $auditPath) { foreach ($item in @(Get-Content -LiteralPath $auditPath -Raw | ConvertFrom-Json)) { $moves.Add($item) } }
function Relocate-File([string]$source, [string]$destination) {
    if (-not (Test-Path -LiteralPath $source)) { return }
    $sourceFull = [IO.Path]::GetFullPath($source)
    $targetFull = [IO.Path]::GetFullPath($destination)
    $roots = @($desk,$docs,$downloads,$hub)
    if (-not ($roots | Where-Object {$sourceFull.StartsWith($_+'\',[StringComparison]::OrdinalIgnoreCase)})) { throw 'Unexpected source.' }
    if (-not ($roots | Where-Object {$targetFull.StartsWith($_+'\',[StringComparison]::OrdinalIgnoreCase)})) { throw 'Unexpected destination.' }
    $file = Get-Item -LiteralPath $sourceFull -Force
    if ($file.PSIsContainer -or $file.Name -eq 'desktop.ini') { throw 'Only selected user files may be moved.' }
    if (Test-Path -LiteralPath $targetFull) { throw "Destination exists: $targetFull" }
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($targetFull)) -Force | Out-Null
    Move-Item -LiteralPath $sourceFull -Destination $targetFull
    $moves.Add([pscustomobject]@{source=$sourceFull;destination=$targetFull;time=(Get-Date).ToString('o')})
    $moves | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $auditPath -Encoding UTF8
}
foreach ($file in @(Get-ChildItem -LiteralPath $downloads -File)) {
    if ($file.Name -eq 'desktop.ini' -or $file.Attributes -band [IO.FileAttributes]::Hidden) { continue }
    $category = switch -Regex ($file.Name) {
        '(?i)(key|token|credential|password)' { 'Private - Credentials'; break }
        '(?i)^alpaca\.txt$' { 'Private - Credentials'; break }
        '(?i)\.(exe|msi|msix)$' { 'Installers'; break }
        '(?i)\.(mp3|m4a|wav|flac)$' { 'Audio'; break }
        '(?i)\.(jpg|jpeg|png|webp|gif)$' { 'Images'; break }
        '(?i)\.(zip|7z|rar)$' { 'Archives'; break }
        '(?i)\.(jar|mcpack)$' { 'Game Mods'; break }
        '(?i)\.(pdf|docx?|xlsx?|pptx?|md|txt)$' { 'Documents'; break }
        default { 'Other Files' }
    }
    Relocate-File $file.FullName (Join-Path $downloads "$category\$($file.Name)")
}
$gameShortcuts = @('Counter-Strike 2.url','OpenSpades (Ace of Spades).lnk','Roblox Player.lnk',"Tom Clancy's Rainbow Six Siege.url",'Ubisoft Connect.lnk','Warframe.url')
foreach ($name in $gameShortcuts) { Relocate-File (Join-Path $desk $name) (Join-Path $desk "Games\$name") }
foreach ($name in @('Chrome Remote Desktop.lnk','Freebuff.lnk','Roblox Studio.lnk')) { Relocate-File (Join-Path $desk $name) (Join-Path $desk "Apps and Tools\$name") }
Relocate-File (Join-Path $desk 'Shutdown after voice.bat') (Join-Path $hub '01 Launchers\Shutdown after voice.bat')
foreach ($file in @(Get-ChildItem -LiteralPath $desk -File -Filter 'Test Results*.html')) {
    Relocate-File $file.FullName (Join-Path $docs "Reports\$($file.Name)")
}
# Existing project roots and app-managed profile/game folders are intentionally stable.
$projects = Join-Path $docs 'Projects'
New-Item -ItemType Directory -Path $projects -Force | Out-Null
$shellLink = New-Object -ComObject WScript.Shell
foreach ($entry in @(
    @{Name='JARVIS Workspace';Target=$hub},
    @{Name='JARVIS Knowledge';Target='C:\Users\Lemab\Documents\JARVIS Knowledge'},
    @{Name='Rocket Frontier';Target='C:\Users\Lemab\Documents\Rocket Frontier'},
    @{Name='Voice Training';Target='C:\Users\Lemab\Documents\KokoroVoice'})) {
    $shortcut=$shellLink.CreateShortcut((Join-Path $projects ($entry.Name+'.lnk')))
    $shortcut.TargetPath=$entry.Target; $shortcut.IconLocation='shell32.dll,3'; $shortcut.Save()
}
$shortcut=$shellLink.CreateShortcut((Join-Path $desk 'My Files.lnk'))
$shortcut.TargetPath=$docs; $shortcut.IconLocation='shell32.dll,3'; $shortcut.Save()
Write-Output "Organized $($moves.Count) personal files and shortcuts. Audit: $auditPath"
