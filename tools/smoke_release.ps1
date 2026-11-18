<#
Проверка собранного релиза так, как его получит человек.

Модульные тесты проверяют исходники, а люди запускают exe, причём чаще всего на
машине с данными прошлой версии или сразу после самообновления. Именно там
ломалось то, что доходило до людей: запуск на чистой установке, падение на
настройках прошлой версии, подмена файла при обновлении. Каждый сценарий ниже —
отдельная папка, программа проходит запуск целиком (`--smoke`: окно, все разделы,
штатный выход) и пишет итог в data\logs\smoke.txt.

    pwsh tools/smoke_release.ps1 -Dist dist [-Previous prev]

-Previous — папка с файлами прошлого релиза. Без неё сценарии «поверх прошлой
версии» пропускаются. Установщик проверяется, только если он собран.
#>
param(
    [string]$Dist = 'dist',
    [string]$Previous = '',
    [string]$Work = (Join-Path ([IO.Path]::GetTempPath()) 'zapretxmel-smoke')
)

$ErrorActionPreference = 'Stop'
$Dist = (Resolve-Path $Dist).Path
$Portable = Join-Path $Dist 'ZapretXmel-Windows-Portable.exe'
$Setup = Join-Path $Dist 'ZapretXmel-Windows-Setup.exe'
$failures = @()

Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $Work | Out-Null

function Stop-Under([string]$Dir) {
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and $_.Path.StartsWith($Dir, [StringComparison]::OrdinalIgnoreCase) } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

function Read-Results([string]$Dir) {
    $file = Join-Path $Dir 'data\logs\smoke.txt'
    if (Test-Path $file) { @(Get-Content $file) } else { @() }
}

# Ждёт, пока в smoke.txt наберётся $Count строк, и проверяет, что все — ok.
function Wait-Results([string]$Dir, [int]$Count, [int]$Seconds = 120) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        $lines = Read-Results $Dir
        if ($lines | Where-Object { $_ -like 'fail*' }) { break }
        if ($lines.Count -ge $Count) { break }
        Start-Sleep 1
    }
    # Перезапущенный экземпляр ещё выходит — даём ему закончить, прежде чем смотреть.
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path.StartsWith($Dir, [StringComparison]::OrdinalIgnoreCase) }) -and
        (Get-Date) -lt $deadline) { Start-Sleep 1 }
    Read-Results $Dir
}

function Show-Log([string]$Dir) {
    $log = Join-Path $Dir 'data\logs\app.log'
    if (Test-Path $log) { Write-Host '--- app.log ---'; Get-Content $log -Tail 60 | Write-Host }
}

function Test-Scenario([string]$Name, [scriptblock]$Body) {
    Write-Host "=== $Name"
    try {
        & $Body
        Write-Host "    годно"
    } catch {
        Write-Host "    ПРОВАЛ: $_"
        $script:failures += "${Name}: $_"
    }
}

# Запускает exe с флагами и ждёт $Count строк итога.
function Invoke-Smoke([string]$Exe, [string[]]$Arguments, [int]$Count = 1) {
    $dir = Split-Path $Exe
    Start-Process $Exe -ArgumentList $Arguments -WorkingDirectory $dir | Out-Null
    $lines = Wait-Results $dir $Count
    if ($lines.Count -lt $Count -or ($lines | Where-Object { $_ -notlike 'ok*' })) {
        Show-Log $dir
        Stop-Under $dir
        throw "итог: $($lines -join ' | ')"
    }
    $lines
}

# --- переносная ---------------------------------------------------------------

Test-Scenario 'Переносная на чистой машине' {
    $dir = Join-Path $Work 'clean'
    New-Item -ItemType Directory $dir | Out-Null
    $exe = Join-Path $dir 'ZapretXmel.exe'
    Copy-Item $Portable $exe
    Invoke-Smoke $exe @('--smoke') | Out-Null
}

Test-Scenario 'Переносная обновляет сама себя' {
    $dir = Join-Path $Work 'self-update'
    New-Item -ItemType Directory $dir | Out-Null
    $exe = Join-Path $dir 'ZapretXmel.exe'
    Copy-Item $Portable $exe
    $lines = Invoke-Smoke $exe @("--smoke-update=$Portable") 2
    if ($lines[0] -notmatch 'update=') { throw "первый запуск не поставил обновление: $($lines[0])" }
    if ($lines[1] -notmatch 'restarted=True') { throw "новая версия запустилась не как после обновления: $($lines[1])" }
    if (Test-Path (Join-Path $dir 'ZapretXmel.new.exe')) { throw 'скачанное осталось лежать рядом' }
    if (-not (Test-Path $exe)) { throw 'программа пропала после обновления' }
}

if ($Previous) {
    $Previous = (Resolve-Path $Previous).Path
    $oldPortable = Get-ChildItem $Previous -Filter 'ZapretXmel-Windows-Portable.exe' | Select-Object -First 1
    if (-not $oldPortable) { $oldPortable = Get-ChildItem $Previous -Filter 'ZapretXmel.exe' | Select-Object -First 1 }

    if ($oldPortable) {
        Test-Scenario 'Переносная поверх данных прошлой версии' {
            $dir = Join-Path $Work 'over-old'
            New-Item -ItemType Directory "$dir\data" -Force | Out-Null
            $exe = Join-Path $dir 'ZapretXmel.exe'
            Copy-Item $oldPortable.FullName $exe
            # Как у человека, который программой уже пользовался: окно знакомства пройдено.
            '{"first_run_done": true, "theme": "dark"}' | Set-Content "$dir\data\config.json" -Encoding utf8
            Start-Process $exe -ArgumentList '--no-elevate' -WorkingDirectory $dir | Out-Null
            Start-Sleep 20
            Stop-Under $dir
            Start-Sleep 2
            Copy-Item $Portable $exe -Force
            Invoke-Smoke $exe @('--smoke') | Out-Null
            $config = Get-Content "$dir\data\config.json" -Raw | ConvertFrom-Json
            if (-not $config.first_run_done) { throw 'новая версия потеряла настройки прошлой' }
        }
    }
}

# --- установщик ---------------------------------------------------------------

function Install-To([string]$SetupExe, [string]$Dir) {
    $log = Join-Path $Work ("setup-" + [IO.Path]::GetRandomFileName() + '.log')
    $setup = Start-Process $SetupExe -PassThru -Wait -ArgumentList `
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=$Dir", "/LOG=$log"
    if ($setup.ExitCode -ne 0) { Get-Content $log | Write-Host; throw "установщик вернул $($setup.ExitCode)" }
    if (-not (Test-Path "$Dir\_internal")) { throw 'установщик не положил сборку папкой' }
}

function Uninstall-From([string]$Dir) {
    Start-Process "$Dir\unins000.exe" -Wait -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
    # Деинсталлятор перезапускает себя копией и сразу возвращает управление.
    $deadline = (Get-Date).AddMinutes(2)
    while ((Test-Path "$Dir\ZapretXmel.exe") -and (Get-Date) -lt $deadline) { Start-Sleep 2 }
    if (Test-Path "$Dir\ZapretXmel.exe") { throw 'удаление не убрало программу' }
    if (Test-Path "$Dir\data") { throw 'удаление оставило данные программы' }
}

if (Test-Path $Setup) {
    Test-Scenario 'Установка, запуск, самообновление и удаление' {
        $dir = Join-Path $Work 'installed'
        Install-To $Setup $dir
        Invoke-Smoke "$dir\ZapretXmel.exe" @('--smoke') | Out-Null
        # Обновление установленной: установщик тихо ставит новую поверх и запускает её.
        $lines = Invoke-Smoke "$dir\ZapretXmel.exe" @("--smoke-update=$Setup") 3
        if ($lines[1] -notmatch 'update=') { throw "обновление не поставилось: $($lines[1])" }
        Uninstall-From $dir
    }

    $oldSetup = if ($Previous) { Get-ChildItem $Previous -Filter 'ZapretXmel-Windows-Setup.exe' | Select-Object -First 1 }
    if ($oldSetup) {
        Test-Scenario 'Установщик поверх прошлой версии' {
            $dir = Join-Path $Work 'installed-over-old'
            Install-To $oldSetup.FullName $dir
            New-Item -ItemType Directory "$dir\data" -Force | Out-Null
            '{"first_run_done": true, "theme": "dark"}' | Set-Content "$dir\data\config.json" -Encoding utf8
            Install-To $Setup $dir
            Invoke-Smoke "$dir\ZapretXmel.exe" @('--smoke') | Out-Null
            Uninstall-From $dir
        }
    }
}

Write-Host ''
if ($failures) {
    Write-Host "Не прошло: $($failures.Count)"
    $failures | ForEach-Object { Write-Host " - $_" }
    exit 1
}
Write-Host 'Все сценарии прошли.'
