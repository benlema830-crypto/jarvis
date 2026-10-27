$ErrorActionPreference = 'Stop'
$hub = 'C:\Users\Lemab\Documents\Jarvis Agent'
$ceo = Join-Path $hub 'Jarvis CEO'
$old = Join-Path $hub "Old Jarvis's"
$report = 'C:\Users\Lemab\jarvis\data\reports\ceo-separation-2026-10-22'
foreach ($path in @($ceo, $old)) {
    if ((Test-Path -LiteralPath $path) -and (Get-ChildItem -LiteralPath $path -Force)) { throw "Destination is not empty: $path" }
}
New-Item -ItemType Directory -Path $ceo, $old, $report -Force | Out-Null
$moves = [System.Collections.Generic.List[object]]::new()
function Move-ProjectItem([string]$source, [string]$destination) {
    $resolved = (Get-Item -LiteralPath $source -Force).FullName
    $allowed = @(($hub + '\'), 'C:\Users\Lemab\Desktop\', 'C:\Users\Lemab\OneDrive\Desktop\')
    if (-not ($allowed | Where-Object { $resolved.StartsWith($_, [StringComparison]::OrdinalIgnoreCase) })) {
        throw "Move source outside the intended workspace or desktop: $resolved"
    }
    if (-not $destination.StartsWith($hub + '\', [StringComparison]::OrdinalIgnoreCase) -and
        -not $destination.StartsWith('C:\Users\Lemab\OneDrive\Desktop\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Move destination outside the intended workspace or desktop: $destination"
    }
    if (Test-Path -LiteralPath $destination) { throw "Destination exists: $destination" }
    Move-Item -LiteralPath $source -Destination $destination
    $moves.Add([pscustomobject]@{source=$source; destination=$destination})
    $moves | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $report 'moves.json') -Encoding UTF8
}
foreach ($name in @('START-HERE.txt','CLAUDE-START-HERE.txt')) {
    Copy-Item -LiteralPath (Join-Path $hub $name) -Destination (Join-Path $report $name)
}
foreach ($name in @('01 Launchers','02 Knowledge','03 Development','04 Plans','05 Reports','06 References','CLAUDE-START-HERE.txt')) {
    Move-ProjectItem (Join-Path $hub $name) (Join-Path $ceo $name)
}
New-Item -ItemType Directory -Path (Join-Path $old 'Launchers') | Out-Null
Move-ProjectItem (Join-Path $ceo '03 Development\Jarvis-Orange') (Join-Path $old 'Jarvis-CustomVoice')
Move-ProjectItem (Join-Path $ceo '03 Development\Jarvis-LocalVoice') (Join-Path $old 'Jarvis-LocalVoice')
Move-ProjectItem (Join-Path $ceo '03 Development\Jarvis-Blue') (Join-Path $ceo '03 Development\Jarvis CEO Source')
foreach ($name in @('Jarvis.lnk','Jarvis - Custom Voice.lnk','Jarvis - Local Voice.lnk','Shutdown after voice.bat')) {
    Move-ProjectItem (Join-Path $ceo ('01 Launchers\' + $name)) (Join-Path $old ('Launchers\' + $name))
}
Move-ProjectItem (Join-Path $ceo '01 Launchers\Open Jarvis Brain.bat') (Join-Path $ceo '01 Launchers\Open Jarvis CEO.bat')
Move-ProjectItem (Join-Path $ceo '01 Launchers\Open Jarvis Agent.bat') (Join-Path $ceo '01 Launchers\Open Jarvis CEO Project.bat')
Move-ProjectItem (Join-Path $ceo '01 Launchers\Jarvis Agent - Codex.lnk') (Join-Path $ceo '01 Launchers\Jarvis CEO - Codex.lnk')
$desktop = 'C:\Users\Lemab\Desktop'
foreach ($name in @('Jarvis - Custom Voice.lnk','Jarvis - Local Voice.lnk','Shutdown after voice.bat')) {
    $source = Join-Path $desktop $name
    if (Test-Path -LiteralPath $source) {
        Move-ProjectItem $source (Join-Path $old ('Launchers\Desktop - ' + $name))
    }
}
$shell = New-Object -ComObject WScript.Shell
function Save-Link([string]$path, [string]$target, [string]$arguments, [string]$workingDirectory) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $target
    $link.Arguments = $arguments
    $link.WorkingDirectory = $workingDirectory
    $link.Save()
}
$devLauncher = Join-Path $ceo '01 Launchers\Open Jarvis CEO Project.bat'
@'
@echo off
title Jarvis CEO - Codex
cd /d "C:\Users\Lemab\Documents\Jarvis Agent\Jarvis CEO"
"C:\Users\Lemab\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe" -C "C:\Users\Lemab\Documents\Jarvis Agent\Jarvis CEO" --add-dir "C:\Users\Lemab\jarvis"
if errorlevel 1 pause
'@ | Set-Content -LiteralPath $devLauncher -Encoding ASCII
Save-Link (Join-Path $ceo '01 Launchers\Jarvis CEO - Codex.lnk') $devLauncher '' $ceo
$codexDesktop = Join-Path $desktop 'Jarvis Agent - Codex.lnk'
if (Test-Path -LiteralPath $codexDesktop) {
    Copy-Item -LiteralPath $codexDesktop -Destination (Join-Path $report 'Desktop Codex before.lnk')
    Move-ProjectItem $codexDesktop (Join-Path $ceo '01 Launchers\Desktop Codex original.lnk')
    Save-Link (Join-Path $desktop 'Jarvis CEO - Codex.lnk') $devLauncher '' $ceo
}
$cloudDesktop = 'C:\Users\Lemab\OneDrive\Desktop'
$brainLink = Join-Path $cloudDesktop 'JARVIS Brain.lnk'
if (Test-Path -LiteralPath $brainLink) {
    Move-ProjectItem $brainLink (Join-Path $cloudDesktop 'Jarvis CEO.lnk')
}
Save-Link (Join-Path $cloudDesktop 'Jarvis CEO.lnk') 'C:\Users\Lemab\jarvis\.venv\Scripts\pythonw.exe' '"C:\Users\Lemab\jarvis\open_brain.py"' 'C:\Users\Lemab\jarvis'
$workspaceLink = Join-Path $cloudDesktop 'JARVIS Workspace.lnk'
if (Test-Path -LiteralPath $workspaceLink) {
    Copy-Item -LiteralPath $workspaceLink -Destination (Join-Path $report 'Workspace before.lnk')
    Save-Link $workspaceLink $ceo '' $ceo
}
Save-Link (Join-Path $cloudDesktop "Old Jarvis's.lnk") $old '' $old
@'
JARVIS PROJECTS

Jarvis CEO     Your active project, previously called Jarvis Brain.
Old Jarvis's   Archived CustomVoice and LocalVoice project links and classic launchers.

Open Jarvis CEO on the desktop to use the app.
Open JARVIS Workspace on the desktop to work on the active project.

Installed code, virtual environments, models, credentials and your Obsidian vault
keep their existing paths. Source folders here are directory links, not copies.
Jarvis CEO still uses the LocalVoice Qwen engine; keep that installation available.
Move records and original shortcut backups: Jarvis CEO\05 Reports\ceo-separation-2026-10-22.
'@ | Set-Content -LiteralPath (Join-Path $hub 'START-HERE.txt') -Encoding UTF8
@'
JARVIS CEO

This is the active Jarvis Brain project, now named Jarvis CEO.
01 Launchers: Open Jarvis CEO.bat starts the app; Jarvis CEO - Codex opens development.
02 Knowledge: your existing Obsidian vault.
03 Development\Jarvis CEO Source: the main repository at C:\Users\Lemab\jarvis.
04 Plans, 05 Reports, 06 References: existing project plans, reports and references.

The assistant, Brain interface, memory and local voice remain part of this project.
The sibling Old Jarvis's folder contains the older assistant variants and launchers.
The installed LocalVoice engine is still required for Jarvis CEO's Qwen voice.
Existing installation paths are preserved to keep virtual environments and models working.
'@ | Set-Content -LiteralPath (Join-Path $ceo 'START-HERE.txt') -Encoding UTF8
@'
OLD JARVIS'S

These older variants are kept for reference. Nothing has been deleted.
Jarvis-CustomVoice: link to C:\Users\Lemab\Documents\Jarvis-CustomVoice.
Jarvis-LocalVoice: link to C:\Users\Lemab\Documents\Jarvis-LocalVoice.
Launchers: previous classic Jarvis, Custom Voice, Local Voice and voice setup helpers.

Jarvis CEO is the active project in the sibling folder.
IMPORTANT: Jarvis CEO still uses the LocalVoice installation's Qwen environment,
models and voice reference files. Archiving its standalone launcher does not disable
the shared voice engine. Do not remove that installation while CEO depends on it.
Source folders are directory links; installed files retain their original paths.
'@ | Set-Content -LiteralPath (Join-Path $old 'START-HERE.txt') -Encoding UTF8
Write-Output 'Workspace separated. Existing runtime paths preserved.'
