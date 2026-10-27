# Makes a self-signed certificate and signs the Cenno binaries with it.
#
# For internal testing only. Windows will trust it on this machine (the
# certificate goes into the trusted root store), but it has no reputation
# outside it: a downloaded file still gets the SmartScreen "Windows protected
# your PC" warning until Cenno is signed with a real certificate.
#
# Usage (from the repository root):
#     powershell -ExecutionPolicy Bypass -File installer\make_test_cert.ps1
#
# Then:
#     build_win.bat
# and the build signs whatever it produces.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$pfx = Join-Path $root "build\cenno-test.pfx"
$password = "cenno"

New-Item -ItemType Directory -Force -Path (Join-Path $root "build") | Out-Null

Write-Host "== creating a self-signed code-signing certificate"
$cert = New-SelfSignedCertificate `
    -Subject "CN=Cenno (test), O=Cenno" `
    -Type CodeSigningCert `
    -CertStoreLocation Cert:\CurrentUser\My `
    -KeyUsage DigitalSignature `
    -NotAfter (Get-Date).AddYears(2)

Export-PfxCertificate -Cert $cert -FilePath $pfx `
    -Password (ConvertTo-SecureString -String $password -Force -AsPlainText) | Out-Null

# Trust it on this machine, so Windows shows a publisher instead of a warning.
Import-Certificate -FilePath $cert.Export("Cert") `
    -CertStoreLocation Cert:\CurrentUser\Root | Out-Null

Write-Host "== certificate saved to $pfx (password: $password)"

# Sign whatever the build produced.
$targets = Get-ChildItem (Join-Path $root "dist") -Filter *.exe -Recurse -ErrorAction SilentlyContinue |
           Where-Object { $_.Name -like "Cenno*.exe" }
if (-not $targets) {
    Write-Host "No Cenno binaries in dist\ yet - run build_win.bat first."
    exit 0
}

foreach ($t in $targets) {
    Write-Host "== signing $($t.FullName)"
    & signtool sign /f $pfx /p $password /fd SHA256 /td SHA256 `
        /tr http://timestamp.digicert.com $t.FullName
    if ($LASTEXITCODE -ne 0) {
        Write-Host "WARNING: could not sign $($t.Name)"
    }
}
