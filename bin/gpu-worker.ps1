# Claudia GPU worker - installer for Windows with an NVIDIA GPU.
#
# Served by the user's OWN box (`slop gpu serve`, nothing from a third-party host except the official uv release,
# Python and the model/package downloads). The line `slop gpu pair` prints runs it:
#   $env:SLOPGPU_URL='https://<box>.trycloudflare.com'; $env:SLOPGPU_TOKEN='<code>'; irm "$env:SLOPGPU_URL/gpu/install.ps1" -Headers @{Authorization="Bearer $env:SLOPGPU_TOKEN"} | iex
# Direct mode (no networking: the bot copied this file and slopgpu-worker.zip into ~\.claudia-gpu\kit first):
#   $env:SLOPGPU_MODE='direct'; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.claudia-gpu\kit\gpu-worker.ps1"
#
# Everything goes under %USERPROFILE%\.claudia-gpu: no admin rights, nothing system-wide, PATH untouched.
#   1. checks for an NVIDIA GPU + driver (CUDA 12.8 wants driver 570 or newer) and free disk space
#   2. downloads uv 0.12.21 from its official GitHub release and checks its SHA-256
#   3. installs a private Python 3.12 with uv
#   4. unpacks the worker code (from the box, or from the kit in direct mode) into app\
#   5. writes slopgpu.cmd, pairs with the box (paired mode) and starts the worker in the background
# Settings (environment): SLOPGPU_URL + SLOPGPU_TOKEN (paired), SLOPGPU_MODE=direct, SLOPGPU_GPU (pin one GPU: its
# UUID or index), SLOPGPU_HOME (default %USERPROFILE%\.claudia-gpu).
# Remove: `& "$env:USERPROFILE\.claudia-gpu\slopgpu.cmd" unpair`, then delete the .claudia-gpu folder.
& {
  $ErrorActionPreference = 'Stop'
  $ProgressPreference = 'SilentlyContinue'      # the progress bar makes Invoke-WebRequest very slow in PowerShell 5
  try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
  $t0 = Get-Date
  $UvVersion = '0.12.21'
  $UvSha = '5d223efa0bf00208c3853246af09420419dfbd352536aa6bb8163d6170e23890'
  $H = if ($env:SLOPGPU_HOME) { $env:SLOPGPU_HOME } else { Join-Path $env:USERPROFILE '.claudia-gpu' }
  $Mode = if ($env:SLOPGPU_MODE) { $env:SLOPGPU_MODE } else { 'paired' }
  function Say([string]$m) { Write-Host "[slopgpu] $m" }
  function Native([string]$exe, [string[]]$a) {
    $old = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $exe @a 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $old }
  }

  if ($Mode -ne 'direct' -and (-not $env:SLOPGPU_URL -or -not $env:SLOPGPU_TOKEN)) {
    throw 'SLOPGPU_URL / SLOPGPU_TOKEN are not set: paste the WHOLE line that `slop gpu pair` printed'
  }
  if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required' }

  # 1. GPU, driver, disk
  $smi = (Get-Command nvidia-smi -ErrorAction SilentlyContinue).Source
  if (-not $smi -and (Test-Path "$env:SystemRoot\System32\nvidia-smi.exe")) { $smi = "$env:SystemRoot\System32\nvidia-smi.exe" }
  if (-not $smi) {
    throw 'no NVIDIA GPU found (nvidia-smi is missing). On Windows the Claudia GPU worker needs an NVIDIA GPU with a current driver; without one the box keeps using its CPU (nothing to install).'
  }
  $gpus = @(Native $smi @('--query-gpu=index,name,memory.total,driver_version', '--format=csv,noheader'))
  Say ('GPUs: ' + ($gpus -join ' | '))
  try {
    $drv = [int](($gpus[0].Split(',')[-1]).Trim().Split('.')[0])
    if ($drv -lt 570) { Say "WARNING: NVIDIA driver $drv is older than 570 (CUDA 12.8 needs 570+). Update it if a profile install fails." }
  } catch { }
  New-Item -ItemType Directory -Force -Path $H, "$H\bin", "$H\logs", "$H\cache" | Out-Null
  try {
    $drive = (Get-Item $H).PSDrive
    if ($drive.Free -lt 15GB) { Say ('WARNING: only {0:N0} GB free on {1}: - the GPU profiles need 5-15 GB' -f ($drive.Free / 1GB), $drive.Name) }
  } catch { }

  # 2. uv (pinned version, checksum-verified)
  $uv = "$H\bin\uv.exe"
  $have = ''
  if (Test-Path $uv) { $have = ((Native $uv @('--version')) -join '') -replace '^uv\s+(\S+).*$', '$1' }
  if ($have -ne $UvVersion) {
    Say "downloading uv $UvVersion (official release)"
    $zip = Join-Path $env:TEMP "slopgpu-uv-$UvVersion.zip"
    Invoke-WebRequest -UseBasicParsing "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip
    $sha = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($sha -ne $UvSha) { Remove-Item -Force $zip; throw "the uv download has the wrong checksum ($sha): refusing it" }
    $tmp = Join-Path $env:TEMP "slopgpu-uv-$UvVersion"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    Copy-Item -Force (Get-ChildItem -Recurse -Path $tmp -Filter 'uv.exe' | Select-Object -First 1).FullName $uv
    Remove-Item -Recurse -Force $tmp, $zip
  }

  # 3. a private Python 3.12 (uv-managed, under $H\python)
  $env:UV_PYTHON_INSTALL_DIR = "$H\python"
  $env:UV_CACHE_DIR = "$H\cache\uv"
  $env:UV_PYTHON_PREFERENCE = 'only-managed'
  $env:UV_NO_CONFIG = '1'
  Say 'installing a private Python 3.12'
  $out = Native $uv @('python', 'install', '3.12')
  if ($LASTEXITCODE -ne 0) { throw ('uv could not install Python 3.12: ' + ($out -join ' ')) }
  $py = ((Native $uv @('python', 'find', '3.12')) | Select-Object -Last 1).Trim()
  if (-not (Test-Path $py)) { throw "Python 3.12 not found after the install ($py)" }

  # 4. the worker code
  $wz = Join-Path $env:TEMP 'slopgpu-worker.zip'
  if ($Mode -eq 'direct') {
    if (-not (Test-Path "$H\kit\slopgpu-worker.zip")) { throw "missing $H\kit\slopgpu-worker.zip: copy the kit first (slop gpu direct-plan)" }
    Copy-Item -Force "$H\kit\slopgpu-worker.zip" $wz
  } else {
    Invoke-WebRequest -UseBasicParsing ($env:SLOPGPU_URL.TrimEnd('/') + '/gpu/worker.zip') -Headers @{ Authorization = "Bearer $env:SLOPGPU_TOKEN" } -OutFile $wz
  }
  if (Test-Path "$H\slopgpu.cmd") { Native "$H\slopgpu.cmd" @('stop') | Out-Null }   # an older worker: stop it first
  if (Test-Path "$H\app.new") { Remove-Item -Recurse -Force "$H\app.new" }
  Expand-Archive -Path $wz -DestinationPath "$H\app.new" -Force
  Remove-Item -Force $wz
  if (Test-Path "$H\app") { Remove-Item -Recurse -Force "$H\app" }
  Move-Item "$H\app.new" "$H\app"

  # 5. launcher, pairing, start. The launcher finds its folder with %~dp0 instead of a written-out path: cmd.exe reads
  #    a .cmd file in the console (OEM) code page, which would garble a home folder with non-ASCII letters.
  $hFull = (Resolve-Path $H).Path.TrimEnd('\')
  $pyRef = $py
  if ($py.StartsWith($hFull + '\', [StringComparison]::OrdinalIgnoreCase)) { $pyRef = '%SLOPGPU_HOME%\' + $py.Substring($hFull.Length + 1) }
  @('@echo off', 'set "SLOPGPU_HOME=%~dp0"', 'set "SLOPGPU_HOME=%SLOPGPU_HOME:~0,-1%"', 'set "PYTHONPATH=%SLOPGPU_HOME%\app"',
    "`"$pyRef`" -m slop.gpu.worker %*") | Set-Content -Encoding Oem "$H\slopgpu.cmd"
  if ($env:SLOPGPU_GPU) {
    $pin = Native "$H\slopgpu.cmd" @('pin', $env:SLOPGPU_GPU)
    if ($LASTEXITCODE -ne 0) { throw ('could not pin GPU ' + $env:SLOPGPU_GPU + ': ' + ($pin -join ' ')) }
    Say "pinned to GPU $env:SLOPGPU_GPU"
  }
  $secs = [int]((Get-Date) - $t0).TotalSeconds
  if ($Mode -eq 'direct') {
    Say "installed in $secs s (direct mode). Next: $H\slopgpu.cmd install audio"
  } else {
    $r = Native "$H\slopgpu.cmd" @('pair', '--url', $env:SLOPGPU_URL)
    Remove-Item Env:SLOPGPU_TOKEN -ErrorAction SilentlyContinue
    if ($LASTEXITCODE -ne 0) { throw ('pairing failed: ' + ($r -join ' ')) }
    $secs = [int]((Get-Date) - $t0).TotalSeconds
    Say "paired and running (installed in $secs s). Go back to the bot - it checks with: slop gpu status"
    Say "this computer: `"$H\slopgpu.cmd`" status | stop | start | logs"
  }
}
