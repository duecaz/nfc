# ============================================================
#  nfc-pi-status.ps1 — estado de servicios en la Pi (ssh)
#  docker ps + health del kiosko + disco + memoria
#    powershell -ExecutionPolicy Bypass -File D:\claude\android\nfc\tools\nfc-pi-status.ps1
# ============================================================

# ---------- CONFIG ----------
$PI = "duecaz@192.168.1.50"
# ----------------------------

try {
    Write-Host "=== nfc PI status ($PI) ===" -ForegroundColor Cyan
    $remote = 'echo "=== contenedores ==="; docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"; echo; echo "=== health kiosko ==="; curl -s http://localhost:8200/health; echo; echo; echo "=== disco / ==="; df -h / | tail -1; echo "=== memoria ==="; free -h | head -2'
    ssh $PI $remote
    if ($LASTEXITCODE -ne 0) { throw "ssh fallo (codigo $LASTEXITCODE)" }
}
catch {
    Write-Host ("!!! ERROR !!!  " + $_.Exception.Message) -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "ENTER para cerrar"
}
