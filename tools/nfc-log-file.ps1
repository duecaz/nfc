# ============================================================
#  nfc-log-file.ps1 — captura el logcat a un archivo (para revisar el error)
#  Muestra en vivo Y guarda. Ctrl+C cuando termines de reproducir el error.
#    powershell -ExecutionPolicy Bypass -File D:\claude\scripts\nfc-log-file.ps1
# ============================================================

# ---------- CONFIG ----------
$PANEL = "192.168.1.57:5555"
$OUT   = "D:\claude\nfc-log.txt"
# ----------------------------

Write-Host "=== adb connect + logcat -> $OUT ===" -ForegroundColor Cyan
adb connect $PANEL
adb -s $PANEL logcat -c
Write-Host "Reproducí el error ahora. Ctrl+C para terminar y guardar." -ForegroundColor Yellow
Write-Host ""
adb -s $PANEL logcat -v time NfcKit:D NfcBridge:D LaNubeKiosk:D AndroidRuntime:E *:E |
    Tee-Object -FilePath $OUT
Write-Host ""
Write-Host "Guardado en $OUT" -ForegroundColor Green
