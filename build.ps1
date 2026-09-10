# Rebuild roadmap.html from the client's own assets. One command.
#
#   .\build.ps1
#
# Run this after a game patch, once you have re-extracted assets in Tomato
# (launch it, click Extract at the Asset Extractor prompt).
# Nothing here touches the network.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here
try {
    # Native commands do NOT honour $ErrorActionPreference in Windows PowerShell 5.1.
    # Without this, a python traceback or a java crash still ended with a green "Done."
    # while the PREVIOUS roadmap.html sat on disk looking freshly built - and got sent.
    function Invoke-Step {
        param([string]$What, [scriptblock]$Do)
        & $Do
        if ($LASTEXITCODE -ne 0) {
            throw ("$What failed (exit $LASTEXITCODE). The error is printed above. " +
                   "Nothing downstream was rebuilt - roadmap.html on disk is still the " +
                   "PREVIOUS build, so do not send it.")
        }
    }

    # Where the extractor and its extracted assets live. Override with ROTMG_TOOLS, or
    # put the assets path in assets-path.txt - the default is a plain sibling folder so
    # a fresh clone asks for a path instead of guessing one.
    $tools  = if ($env:ROTMG_TOOLS) { $env:ROTMG_TOOLS } else { Join-Path $here '..\rotmg-assets' }
    $sheet  = Join-Path $tools 'assets\flatbuffer\spritesheetf'
    $build  = Join-Path $here '.build'

    # Take whatever Tomato is present, newest first. Pinning the exact filename meant a
    # Tomato upgrade broke this with a bare "file not found".
    # Sort by PARSED VERSION, not by name. A plain Name sort puts "Tomato-v1.10.0.jar"
    # BELOW "Tomato-v1.9.2.jar" (because '1' < '9'), so the newest jar would be silently
    # ignored - and the change warning below would never fire either, because from the
    # script's point of view the jar never changed.
    $jars = @(Get-ChildItem (Join-Path $tools 'Tomato-*.jar') -ErrorAction SilentlyContinue)
    if (-not $jars) {
        throw ("No Tomato-*.jar found in $tools. That jar is what decodes the client's " +
               "sprite sheet; without it there are no sprites to pack.")
    }
    $jar = $jars | Sort-Object @{ Expression = {
               $m = [regex]::Match($_.Name, '(\d+)\.(\d+)\.(\d+)')
               if ($m.Success) { [version]("{0}.{1}.{2}" -f $m.Groups[1].Value, $m.Groups[2].Value, $m.Groups[3].Value) }
               else { [version]'0.0.0' } } } -Descending | Select-Object -First 1
    if ($jars.Count -gt 1) {
        Write-Host "  ! $($jars.Count) Tomato jars present; using the newest: $($jar.Name)" -ForegroundColor Yellow
    }
    $jarName = $jar.Name
    $jar     = $jar.FullName

    # javac: JAVA_HOME, then PATH, then the newest JDK under Program Files.
    # This used to be a hard-coded jdk-25 path, so the build ran on exactly one machine.
    $javac = $null
    if ($env:JAVA_HOME -and (Test-Path (Join-Path $env:JAVA_HOME 'bin\javac.exe'))) {
        $javac = Join-Path $env:JAVA_HOME 'bin\javac.exe'
    }
    if (-not $javac) {
        $cmd = Get-Command javac.exe -ErrorAction SilentlyContinue
        if ($cmd) { $javac = $cmd.Source }
    }
    if (-not $javac) {
        $cand = Get-ChildItem 'C:\Program Files\Java\jdk-*\bin\javac.exe' -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending | Select-Object -First 1
        if ($cand) { $javac = $cand.FullName }
    }
    if (-not $javac) { throw 'javac.exe not found. Set JAVA_HOME, or put a JDK on PATH.' }

    if (-not (Test-Path $sheet)) { throw "spritesheetf not found - re-extract assets in Tomato first" }
    New-Item -ItemType Directory -Force $build | Out-Null

    # DumpSprites.java compiles against Tomato's OWN generated FlatBuffers classes, so the
    # jar that built the sprite index is part of this data's provenance. Record it, and say
    # so out loud when it changes - a different Tomato can shift the sprite indices.
    $stamp = Join-Path $build 'tomato-jar.txt'
    if (Test-Path $stamp) {
        $prev = (Get-Content $stamp -Raw).Trim()
        if ($prev -ne $jarName) {
            Write-Host "  ! sprite index was last built with $prev, now using $jarName - spot-check a few sprites." -ForegroundColor Yellow
        }
    }
    Set-Content -Path $stamp -Value $jarName -Encoding utf8

    Write-Host "  jar   $jarName" -ForegroundColor DarkGray
    Write-Host "  javac $javac"   -ForegroundColor DarkGray

    # 1. sprite atlas index — compiled against Tomato's own FlatBuffers classes,
    #    because the schema is theirs and their decoder is the one that agrees with the file.
    Write-Host '[1/3] dumping sprite index...' -ForegroundColor Cyan
    Invoke-Step 'compiling DumpSprites' { & $javac -nowarn -cp $jar -d $build (Join-Path $here 'DumpSprites.java') }
    Invoke-Step 'dumping the sprite index' { & java -cp "$jar;$build" DumpSprites $sheet (Join-Path $build 'sprites.tsv') }

    # DumpSprites can exit 0 and still produce a half-useless index. Without the ANIMATED
    # half no *Chars* sheet exists in the dump at all, and no dungeon boss can resolve to
    # its real art - exactly the regression that once shipped 39 bosses as scenery.
    $tsv = Join-Path $build 'sprites.tsv'
    if (-not (Select-String -Path $tsv -Pattern '^s	' -Quiet)) {
        throw "sprites.tsv has no static sprite rows - re-extract assets in Tomato, then re-run."
    }
    if (-not (Select-String -Path $tsv -Pattern '^a	' -Quiet)) {
        throw ("sprites.tsv has no ANIMATED sprite rows. Every dungeon boss is drawn from " +
               "that half, so Tomato's AnimatedSprite API has changed shape and " +
               "DumpSprites.java needs updating before this data can be trusted.")
    }

    # 2. crop + pack the item sprites
    Write-Host '[2/3] packing sprites...' -ForegroundColor Cyan
    Invoke-Step 'packing sprites' { & python (Join-Path $here 'build-sprites.py') }

    # 3. parse the XML and inline everything into the single file
    Write-Host '[3/3] building roadmap.html...' -ForegroundColor Cyan
    Invoke-Step 'building roadmap.html' { & python (Join-Path $here 'build-data.py') }

    Write-Host "`nDone. Send roadmap.html to anyone - it needs nothing installed." -ForegroundColor Green
}
finally { Pop-Location }
