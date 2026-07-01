# ============================================================
#  nfc-versions.ps1 — muestra la version de la WEB (Pi) y del APK (panel)
#    powershell -ExecutionPolicy Bypass -File D:\claude\scripts\nfc-versions.ps1
# ============================================================

# ---------- CONFIG ----------
$PANEL  = "192.168.1.57:5555"
$HEALTH = "https://lanube.uno/health"
$PKG    = "uno.lanube.kiosk"
# ----------------------------

try {
    Write-Host "=== WEB (Pi) ===" -ForegroundColor Cyan
    try {
        $h = Invoke-RestMethod -Uri $HEALTH -TimeoutSec 10
        Write-Host ("  web version:  v{0}   (usuarios: {1})" -f $h.version, $h.users) -ForegroundColor Green
    } catch {
        Write-Host ("  no se pudo leer {0}  ({1})" -f $HEALTH, $_.Exception.Message) -ForegroundColor Yellow
    }

    Write-Host ""
    Write-Host "=== APK (panel) ===" -ForegroundColor Cyan
    adb connect $PANEL | Out-Null
    adb -s $PANEL shell monkey -p $PKG 1 | Out-Null
    Start-Sleep -Seconds 2
    $m = adb -s $PANEL logcat -d -s LaNubeKiosk:D | Select-String "APK v\d+" | Select-Object -Last 1
    if ($m) {
        $v = [regex]::Match($m.Line, "APK v\d+").Value
        Write-Host ("  {0}" -f $v) -ForegroundColor Green
    } else {
        Write-Host "  no encontre 'APK vN' en el log (relanza el kiosko y reintenta)" -ForegroundColor Yellow
    }
}
catch {
    Write-Host ("!!! ERROR !!!  " + $_.Exception.Message) -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "ENTER para cerrar"
}
