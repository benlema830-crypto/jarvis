$ErrorActionPreference = 'Stop'
$hub = 'C:\Users\Lemab\Documents\Jarvis Agent'
$repo = 'C:\Users\Lemab\jarvis'
$desktopPath = [Environment]::GetFolderPath('Desktop')
$auditPath = Join-Path $repo 'data\organization-log.json'
$moves = [System.Collections.Generic.List[object]]::new()
if (Test-Path -LiteralPath $auditPath) {
    foreach ($entry in @(Get-Content -LiteralPath $auditPath -Raw | ConvertFrom-Json)) { $moves.Add($entry) }
}
foreach ($folder in @('01 Launchers','03 Development','06 References\Video screenshots','06 References\UI previews')) {
    New-Item -ItemType Directory -Path (Join-Path $hub $folder) -Force | Out-Null
}
foreach ($folder in @('docs\plans','data\reports')) {
    New-Item -ItemType Directory -Path (Join-Path $repo $folder) -Force | Out-Null
}
function Move-Recorded([string]$source, [string]$destination) {
    if (-not (Test-Path -LiteralPath $source)) { return }
    $sourceFull = [IO.Path]::GetFullPath($source)
    $destinationFull = [IO.Path]::GetFullPath($destination)
    $allowed = @($hub, $repo, $desktopPath, 'C:\Users\Lemab\OneDrive\Pictures\Screenshots')
    if (-not ($allowed | Where-Object { $sourceFull.StartsWith($_ + '\', [StringComparison]::OrdinalIgnoreCase) })) { throw 'Source outside selected JARVIS locations.' }
    if (-not ($destinationFull.StartsWith($hub + '\', [StringComparison]::OrdinalIgnoreCase) -or $destinationFull.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase))) { throw 'Destination outside JARVIS workspace.' }
    $item = Get-Item -LiteralPath $sourceFull -Force
    if ($item.PSIsContainer) {
        $targets = @('C:\Users\Lemab\jarvis','C:\Users\Lemab\Documents\Jarvis-CustomVoice','C:\Users\Lemab\Documents\Jarvis-LocalVoice')
        if ($item.LinkType -ne 'Junction' -or $item.Target[0] -notin $targets) { throw 'Only verified JARVIS directory links may be moved.' }
    }
    if (Test-Path -LiteralPath $destinationFull) { throw "Destination already exists: $destinationFull" }
    Move-Item -LiteralPath $sourceFull -Destination $destinationFull
    $moves.Add([pscustomobject]@{source=$sourceFull;destination=$destinationFull;time=(Get-Date).ToString('o')})
    $moves | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $auditPath -Encoding UTF8
}
foreach ($name in @('Jarvis-Blue','Jarvis-Orange','Jarvis-LocalVoice')) {
    Move-Recorded (Join-Path $hub $name) (Join-Path $hub "03 Development\$name")
}
foreach ($name in @('Open Jarvis Agent.bat','Open Jarvis Brain.bat')) {
    Move-Recorded (Join-Path $hub $name) (Join-Path $hub "01 Launchers\$name")
}
foreach ($name in @('Jarvis.lnk','Jarvis - Custom Voice.lnk','Jarvis - Local Voice.lnk','Jarvis Agent - Codex.lnk')) {
    Move-Recorded (Join-Path $desktopPath $name) (Join-Path $hub "01 Launchers\$name")
}
Move-Recorded (Join-Path $repo 'NIGHT-BUILD-PROMPT.txt') (Join-Path $repo 'docs\plans\NIGHT-BUILD-PROMPT.txt')
foreach ($name in @('brain-preview.png','brain-atmosphere.png')) {
    Move-Recorded (Join-Path $repo "data\$name") (Join-Path $hub "06 References\UI previews\$name")
}
foreach ($stamp in @('233642','233653','233730','233823','233902','233931','234004','235842')) {
    $name = "Screenshot 2026-10-20 $stamp.png"
    Move-Recorded "C:\Users\Lemab\OneDrive\Pictures\Screenshots\$name" (Join-Path $hub "06 References\Video screenshots\$name")
}
$links = @{
    '02 Knowledge' = 'C:\Users\Lemab\Documents\JARVIS Knowledge'
    '04 Plans' = 'C:\Users\Lemab\jarvis\docs\plans'
    '05 Reports' = 'C:\Users\Lemab\jarvis\data\reports'
}
foreach ($name in $links.Keys) {
    $path = Join-Path $hub $name
    if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType Junction -Path $path -Target $links[$name] | Out-Null }
}
$shellLink = New-Object -ComObject WScript.Shell
$shortcut = $shellLink.CreateShortcut((Join-Path $desktopPath 'JARVIS Workspace.lnk'))
$shortcut.TargetPath = $hub
$shortcut.IconLocation = 'shell32.dll,3'
$shortcut.Description = 'JARVIS launchers, knowledge, source, plans, reports, and references'
$shortcut.Save()
$codexLink = Join-Path $hub '01 Launchers\Jarvis Agent - Codex.lnk'
if (Test-Path -LiteralPath $codexLink) {
    $shortcut = $shellLink.CreateShortcut($codexLink)
    if ($shortcut.TargetPath -like '*Open Jarvis Agent.bat') {
        $shortcut.TargetPath = Join-Path $hub '01 Launchers\Open Jarvis Agent.bat'
        $shortcut.Save()
    }
}
Write-Output "Organized $($moves.Count) entries. Audit: $auditPath"
