# ============================================================
#  nfc-capture.ps1 — foto de la pantalla del panel (para revisar el error)
#  screencap en el panel -> pull a la PC -> abre la imagen
#    powershell -ExecutionPolicy Bypass -File D:\claude\scripts\nfc-capture.ps1
# ============================================================

# ---------- CONFIG ----------
$PANEL = "192.168.1.57:5555"
$OUT   = "D:\claude\captura.png"
# ----------------------------

try {
    Write-Host "=== adb connect + captura -> $OUT ===" -ForegroundColor Cyan
    adb connect $PANEL
    adb -s $PANEL shell screencap -p /sdcard/screen.png
    adb -s $PANEL pull /sdcard/screen.png $OUT
    adb -s $PANEL shell rm /sdcard/screen.png
    if (Test-Path $OUT) {
        Write-Host "Captura guardada en $OUT" -ForegroundColor Green
        Start-Process $OUT   # abre la imagen para revisarla
    } else {
        throw "no se pudo guardar la captura"
    }
}
catch {
    Write-Host ("!!! ERROR !!!  " + $_.Exception.Message) -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "ENTER para cerrar"
}
