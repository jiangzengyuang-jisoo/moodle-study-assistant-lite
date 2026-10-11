$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& '.venv/Scripts/python.exe' -X utf8 tools/release/package_source.py
if ($LASTEXITCODE -ne 0) { throw 'Source packaging failed.' }
