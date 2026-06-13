"""
Kiosko NFC -> Nextcloud (lanube.uno)
-------------------------------------
Mini-servicio que loguea a un docente en Nextcloud usando solo el UID de su
tarjeta NFC (el lector USB "teclea" el UID como un teclado).

Flujo:
  1. El navegador (pantalla) muestra la pagina kiosko con un campo enfocado.
  2. El docente pasa la tarjeta -> el lector escribe el UID + Enter.
  3. La pagina hace POST /auth con el UID.
  4. Este servicio busca el UID en users.json -> {usuario, token/password}.
  5. Hace el login contra Nextcloud por detras (handshake con requesttoken).
  6. Reenvia las cookies de sesion al navegador (mismo host) y redirige a Archivos.

El token/password NUNCA llega al navegador.

CREDENCIALES EN users.json:
  Formato preferido -> { "user": "jperez", "token": "xxxx-yyyy-zzzz" }
  Formato legado   -> { "user": "jperez", "password": "ClaveReal123" }
  El campo 'token' tiene prioridad. Si el docente cambia su contrasena real,
  el NFC sigue funcionando siempre que el token no se haya revocado.
"""
import json
import os
import re
from pathlib import Path

import requests
from flask import Flask, jsonify, make_response, render_template, request

app = Flask(__name__)

NEXTCLOUD_URL = os.environ.get("NEXTCLOUD_URL", "http://192.168.1.50:8181")
NEXTCLOUD_PUBLIC_URL = os.environ.get("NEXTCLOUD_PUBLIC_URL", NEXTCLOUD_URL)
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN") or None
COOKIE_SECURE = NEXTCLOUD_PUBLIC_URL.startswith("https")

USERS_FILE = Path(__file__).parent / "users.json"

REQUESTTOKEN_RE = re.compile(r'name="requesttoken"\s+value="([^"]+)"')
HEAD_TOKEN_RE = re.compile(r'data-requesttoken="([^"]+)"')


def load_users():
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {}


def get_requesttoken(html):
    m = REQUESTTOKEN_RE.search(html) or HEAD_TOKEN_RE.search(html)
    return m.group(1) if m else None


@app.route("/")
def index():
    return render_template("index.html", nextcloud_url=NEXTCLOUD_PUBLIC_URL)


@app.route("/auth", methods=["POST"])
def auth():
    uid = (request.form.get("uid") or "").strip()
    if not uid:
        return jsonify(ok=False, error="UID vacio"), 400

    users = load_users()
    record = users.get(uid)
    if not record:
        return jsonify(ok=False, error="Tarjeta no registrada", uid=uid), 404

    username = record["user"]
    # Preferir 'token' (app password revocable) sobre 'password' (clave real).
    # Asi el docente puede cambiar su contrasena sin romper el acceso NFC.
    credential = record.get("token") or record.get("password")
    using_token = bool(record.get("token"))

    if not credential:
        print(f"[AUTH] ERROR: sin credencial para uid={uid}", flush=True)
        return jsonify(ok=False, error="Sin credencial configurada para esta tarjeta"), 500

    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (kiosk)"})
    try:
        login_page = s.get(f"{NEXTCLOUD_URL}/login", timeout=15)
    except requests.RequestException as exc:
        print(f"[AUTH] ERROR contacto NC: {exc}", flush=True)
        return jsonify(ok=False, error=f"No se pudo contactar Nextcloud: {exc}"), 502

    cookie_vals = {c.name: c.value for c in s.cookies}
    print(f"[AUTH] GET /login -> {login_page.status_code} cookies={cookie_vals}",
          flush=True)

    token = get_requesttoken(login_page.text)
    if not token:
        print("[AUTH] ERROR: no se encontro requesttoken en el HTML", flush=True)
        return jsonify(ok=False, error="No se obtuvo requesttoken"), 502

    cred_type = "token" if using_token else "password"
    print(f"[AUTH] requesttoken={token[:12]}... user={username} cred={cred_type}",
          flush=True)

    data = {
        "user": username,
        "password": credential,
        "requesttoken": token,
        "timezone": "America/Lima",
        "timezone_offset": "-5",
        "rememberme": "true",
    }
    resp = s.post(
        f"{NEXTCLOUD_URL}/login",
        data=data,
        headers={
            "requesttoken": token,
            # Nextcloud rechaza el login (CSRF) si falta Origin o no coincide con el
            # host publico -> apuntamos al dominio publico real.
            "Origin": NEXTCLOUD_PUBLIC_URL,
            "Referer": f"{NEXTCLOUD_PUBLIC_URL}/login",
        },
        allow_redirects=False,
        timeout=10,
    )

    location = resp.headers.get("Location", "")
    body_snippet = resp.text[:300].replace("\n", " ")
    print(f"[AUTH] POST /login -> status={resp.status_code} "
          f"location={location!r} cookies={[c.name for c in s.cookies]}", flush=True)
    print(f"[AUTH] body[:300]={body_snippet!r}", flush=True)

    if "/login" in location or resp.status_code not in (301, 302, 303):
        print(f"[AUTH] RECHAZADO para user={username} (cred={cred_type})", flush=True)
        return jsonify(ok=False, error="Credenciales rechazadas por Nextcloud"), 401

    print(f"[AUTH] OK login user={username} cred={cred_type} -> {location}", flush=True)

    out = make_response(jsonify(ok=True, redirect=f"{NEXTCLOUD_PUBLIC_URL}/apps/files",
                                user=username))
    for c in s.cookies:
        # Las cookies __Host- no admiten atributo Domain (el navegador las rechaza).
        # Nextcloud las regenera solo al entrar al dominio publico, asi que las saltamos.
        if COOKIE_DOMAIN and c.name.startswith("__Host-"):
            continue
        out.set_cookie(c.name, c.value, path="/", httponly=True, samesite="Lax",
                       domain=COOKIE_DOMAIN, secure=COOKIE_SECURE)
    return out


@app.route("/health")
def health():
    users = load_users()
    token_count = sum(1 for v in users.values() if v.get("token"))
    pass_count = sum(1 for v in users.values() if v.get("password") and not v.get("token"))
    return jsonify(
        ok=True,
        users=len(users),
        con_token=token_count,
        con_password=pass_count,
        nextcloud=NEXTCLOUD_URL,
        public=NEXTCLOUD_PUBLIC_URL,
        cookie_domain=COOKIE_DOMAIN,
    )


@app.route("/sw.js")
def sw_js():
    """
    Service worker auto-destructor.

    Toma el control inmediatamente (skipWaiting + claim), borra todos los
    caches y se desregistra. NO navega a los clientes: la pagina /reset
    es la que controla la navegacion final para evitar bucles.
    """
    js = """\
// Auto-destructor SW - La Nube kiosko NFC
self.addEventListener('install', (e) => {
    self.skipWaiting();
    e.waitUntil(
        caches.keys().then(ks => Promise.all(ks.map(k => caches.delete(k))))
    );
});

self.addEventListener('activate', (e) => {
    // Solo tomamos control y nos desregistramos.
    // NO hacemos c.navigate() - /reset controla la navegacion para evitar bucles.
    e.waitUntil(
        self.clients.claim()
            .then(() => self.registration.unregister())
    );
});

// Passthrough puro mientras esta activo - no cachea nada
self.addEventListener('fetch', (e) => {
    e.respondWith(fetch(e.request));
});
"""
    resp = make_response(js)
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-store, no-cache"
    return resp


@app.route("/reset")
def reset():
    """
    Limpieza de pantallas atascadas por SW fantasma de Nextcloud.

    RESTRICCION DE HARDWARE: las pantallas interactivas NO tienen F12 ni
    DevTools. La unica forma de acceder es escribir la URL en la barra del
    navegador usando el teclado virtual de la pantalla tactil.

    Flujo de limpieza:
      1. JS desregistra todos los SWs activos via getRegistrations().
      2. Limpia Cache API, localStorage y sessionStorage.
      3. Registra el SW destructor (/sw.js) como segunda capa para cubrir
         SWs en estado 'waiting' que no aparecen en getRegistrations.
         El SW NO navega clientes (evita el bucle /reset -> /reset).
      4. Muestra boton verde 'Abrir kiosko NFC' + auto-redirect a / con
         delay para que el SW termine de desregistrarse antes de navegar.

    Por que no alcanza con Clear-Site-Data:
      Ese header no puede desregistrar SWs (no existe esa opcion en la
      spec del navegador). Solo borra la Cache HTTP y localStorage.
    """
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reparando pantalla…</title>
</head>
<body style="background:#0a2540;color:#fff;font-family:sans-serif;
            text-align:center;padding-top:20vh;padding-left:1rem;padding-right:1rem">
  <h1>&#x1F9F9; Limpiando pantalla…</h1>
  <p id="st" style="opacity:.8;font-size:1.2rem;margin-top:1rem">Iniciando…</p>
  <div id="btn" style="display:none;margin-top:2.5rem">
    <a href="/" style="display:inline-block;padding:1rem 2.5rem;
       background:#3ddc97;color:#0a2540;border-radius:12px;
       text-decoration:none;font-size:1.3rem;font-weight:700">
      Abrir kiosko NFC &#x2192;
    </a>
  </div>
<script>
(async () => {
  const st = document.getElementById('st');
  const btn = document.getElementById('btn');
  const log = [];

  // 1. Desregistrar todos los SW activos o en espera
  if ('serviceWorker' in navigator) {
    try {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map(r => r.unregister()));
      log.push('SW eliminados: ' + regs.length);
    } catch (e) { log.push('SW error: ' + e.message); }
  }

  // 2. Limpiar Cache API
  if (window.caches) {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map(k => caches.delete(k)));
      log.push('Caches: ' + keys.length);
    } catch (e) {}
  }

  // 3. Limpiar storage
  try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}

  // 4. Registrar SW destructor como segunda capa.
  //    El SW no navega clientes - nosotros controlamos la navegacion
  //    desde aqui para no caer en bucle /reset -> /reset.
  if ('serviceWorker' in navigator) {
    try {
      await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      await new Promise(r => setTimeout(r, 1000));
      log.push('Destructor: OK');
    } catch (e) { log.push('Destructor: ' + e.message); }
  }

  st.textContent = '✅ ' + log.join(' · ');

  // Mostrar boton manual - el usuario toca cuando quiera
  btn.style.display = 'block';

  // Auto-redirect de respaldo (2 s extra para que el SW se desregistre)
  setTimeout(() => { window.location.replace('/'); }, 2000);
})();
</script>
</body>
</html>"""
    resp = make_response(html)
    resp.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
