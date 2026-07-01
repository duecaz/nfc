# ============================================================
#  nfc-web-pi.ps1 — Deploy web a la Raspberry Pi
#  ssh Pi -> baja web/ desde GitHub (main) -> docker rebuild -> health
#  NO usa el repo local: la fuente es GitHub main (lo actualiza Claude).
#    powershell -ExecutionPolicy Bypass -File D:\claude\scripts\nfc-web-pi.ps1
# ============================================================

# ---------- CONFIG ----------
$PI = "duecaz@192.168.1.50"
# ----------------------------

try {
    Write-Host "=== nfc WEB deploy Pi ($PI) ===" -ForegroundColor Cyan
    Write-Host "La Pi baja web/ desde GitHub (rama main) y reconstruye Docker." -ForegroundColor DarkGray
    Write-Host ""

    $remote = 'cd ~/docker/kiosk && for f in app.py templates/index.html templates/login_manual.html templates/cambiar_clave.html templates/admin.html; do curl -fsSL -o "$f" "https://raw.githubusercontent.com/duecaz/nfc/main/web/$f"; done && docker compose down && docker compose build --no-cache && docker compose up -d && sleep 5 && echo "--- health ---" && curl -s http://localhost:8200/health && echo'
    ssh $PI $remote
    if ($LASTEXITCODE -ne 0) { throw "deploy ssh fallo (codigo $LASTEXITCODE)" }

    Write-Host ""
    Write-Host "OK. Si el panel muestra version vieja -> lanube.uno/reset" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host ("!!! ERROR !!!  " + $_.Exception.Message) -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "ENTER para cerrar"
}
