# ============================================================
#  nfc-clear.ps1 — borra cookies/datos del kiosko y lo relanza
#    powershell -ExecutionPolicy Bypass -File D:\claude\scripts\nfc-clear.ps1
# ============================================================

# ---------- CONFIG ----------
$PANEL = "192.168.1.57:5555"
$PKG   = "uno.lanube.kiosk"
# ----------------------------

try {
    Write-Host "=== adb connect + pm clear + relanzar ===" -ForegroundColor Cyan
    adb connect $PANEL
    adb -s $PANEL shell pm clear $PKG
    adb -s $PANEL shell monkey -p $PKG 1
    Write-Host "Cookies/datos borrados y kiosko relanzado." -ForegroundColor Green
}
catch {
    Write-Host ("!!! ERROR !!!  " + $_.Exception.Message) -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "ENTER para cerrar"
}
