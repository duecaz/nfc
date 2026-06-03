# ============================================================================
# Test rápido del login NFC "dazzle" SIN instalar nada.
#
# Mira el perfil de usuario activo de Android por adb. Como en este panel la
# tarjeta NFC cambia de perfil (lo hace el servicio dazzle), cada vez que
# acercás una tarjeta este script detecta el cambio y muestra el "login".
#
# Uso:
#   1) Conectá el panel por adb (adb connect 192.168.1.43:5555).
#   2) En PowerShell:  .\nfc-login-watch.ps1
#   3) Acercá las tarjetas al lector del panel y mirá la consola.
# ============================================================================

# Mapa  perfil (user id) -> nombre de cuenta. Ajustalo a tus perfiles/tarjetas.
$users = @{
    "0"  = "Administrador"
    "10" = "profe1"
    # "11" = "profe2"
}

Write-Host "Vigilando el perfil activo... (Ctrl+C para salir)" -ForegroundColor Cyan
$last = ""
while ($true) {
    $u = (adb shell am get-current-user 2>$null).Trim()
    if ($u -and $u -ne $last) {
        $name = $users[$u]
        if (-not $name) { $name = "perfil $u (SIN MAPEAR)" }
        $ts = Get-Date -Format "HH:mm:ss"
        Write-Host ("[{0}]  Sesion iniciada: {1}   (user {2})" -f $ts, $name, $u) -ForegroundColor Green
        $last = $u
    }
    Start-Sleep -Milliseconds 700
}
