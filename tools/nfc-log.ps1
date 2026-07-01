# ============================================================
#  nfc-log.ps1 — logcat NFC en vivo (errores en directo)
#  Ctrl+C para salir.
#    powershell -ExecutionPolicy Bypass -File D:\claude\android\nfc\tools\nfc-log.ps1
# ============================================================

# ---------- CONFIG ----------
$PANEL = "192.168.1.57:5555"
# ----------------------------

Write-Host "=== adb connect + logcat NFC (Ctrl+C para salir) ===" -ForegroundColor Cyan
adb connect $PANEL
adb -s $PANEL logcat -c
Write-Host "Acerca la tarjeta / logueá y mira las lineas NfcKit / NfcBridge / LaNubeKiosk." -ForegroundColor Yellow
Write-Host ""
adb -s $PANEL logcat -v time -s NfcKit:* NfcBridge:* LaNubeKiosk:* AndroidRuntime:E
