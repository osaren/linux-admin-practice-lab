# The shared Python CLI owns all guest and lifecycle operations.
$ErrorActionPreference = 'Stop'
$entryPoint = Join-Path $PSScriptRoot 'lib/lfcs.py'
$launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue
if ($launcher) {
    & $launcher.Source -3 -X utf8 $entryPoint @args
    exit $LASTEXITCODE
}
$python = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue
if (!$python) {
    [Console]::Error.WriteLine('Python 3.9 or newer is required. See docs/install-windows.md.')
    exit 1
}
& $python.Source -X utf8 $entryPoint @args
exit $LASTEXITCODE
