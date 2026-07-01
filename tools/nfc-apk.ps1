# ============================================================
#  nfc-apk.ps1 — Kiosko Android .NET (uno.lanube.kiosk)
#  git main -> build Release -> adb install -> run
#    powershell -ExecutionPolicy Bypass -File D:\claude\android\nfc\tools\nfc-apk.ps1
# ============================================================

# ---------- CONFIG (ajustá $REPO si tu repo esta en otra ruta) ----------
$REPO   = "D:\claude\android\nfc"
$PANEL  = "192.168.1.57:5555"
$PKG    = "uno.lanube.kiosk"
$CSPROJ = "apk\KioskNfc.csproj"
# ------------------------------------------------------------------------

try {
    Set-Location $REPO
    Write-Host "=== nfc APK: git -> build -> adb -> run ===" -ForegroundColor Cyan

    # 1. git (SIEMPRE main).
    Write-Host "=== 1/5  git (main) ===" -ForegroundColor Cyan
    git fetch origin main
    git checkout main
    git reset --hard origin/main
    if ($LASTEXITCODE -ne 0) { throw "git fallo" }

    # 2. build Release (limpio).
    Write-Host "=== 2/5  build Release ===" -ForegroundColor Cyan
    Remove-Item apk\bin, apk\obj -Recurse -Force -ErrorAction SilentlyContinue
    dotnet build $CSPROJ -c Release
    if ($LASTEXITCODE -ne 0) { throw "build fallo" }

    $APK = Get-ChildItem "apk\bin\Release\*\*-Signed.apk" -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if (-not $APK) { throw "no se encontro el APK -Signed en apk\bin\Release" }
    Write-Host ("APK: " + $APK.FullName) -ForegroundColor DarkGray

    # 3. adb connect (siempre antes de comandos adb).
    Write-Host "=== 3/5  adb connect ===" -ForegroundColor Cyan
    adb connect $PANEL

    # 4. install (reemplaza; si falla, uninstall + install limpio).
    Write-Host "=== 4/5  install ===" -ForegroundColor Cyan
    adb -s $PANEL install -r $APK.FullName
    if ($LASTEXITCODE -ne 0) {
        Write-Host "install -r fallo -> uninstall + install limpio" -ForegroundColor Yellow
        adb -s $PANEL uninstall $PKG
        adb -s $PANEL install $APK.FullName
        if ($LASTEXITCODE -ne 0) { throw "install fallo" }
    }

    # 5. run.
    Write-Host "=== 5/5  run ===" -ForegroundColor Cyan
    adb -s $PANEL shell monkey -p $PKG 1
    Write-Host "OK. Confirma la etiqueta 'apk vN' abajo-izquierda del kiosko." -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host ("!!! ERROR !!!  " + $_.Exception.Message) -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "ENTER para cerrar"
}
