# ============================================================
#  nfc-web-pi.ps1 — Deploy web a la Raspberry Pi
#  push main -> ssh Pi -> curl main/web + docker rebuild + health
#    powershell -ExecutionPolicy Bypass -File D:\claude\android\nfc\tools\nfc-web-pi.ps1
# ============================================================

# ---------- CONFIG ----------
$REPO = "D:\claude\android\nfc"
$PI   = "duecaz@192.168.1.50"
# ----------------------------

try {
    Set-Location $REPO
    Write-Host "=== nfc WEB deploy Pi ===" -ForegroundColor Cyan

    # 1. push main (por si hay commits locales sin subir).
    Write-Host "=== 1/2  push main ===" -ForegroundColor Cyan
    git push origin main
    # (si dice 'Everything up-to-date' esta ok, seguimos)

    # 2. ssh a la Pi: baja web/ desde main y reconstruye Docker.
    Write-Host "=== 2/2  ssh deploy en la Pi ($PI) ===" -ForegroundColor Cyan
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
