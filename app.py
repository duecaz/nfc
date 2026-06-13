"""
Kiosko NFC -> Nextcloud (lanube.uno)
-------------------------------------
Mini-servicio que loguea a un docente en Nextcloud usando solo el UID de su
tarjeta NFC (el lector USB "teclea" el UID como un teclado).

Flujo:
  1. El navegador (pantalla) muestra la pagina kiosko con un campo enfocado.
  2. El docente pasa la tarjeta -> el lector escribe el UID + Enter.
  3. La pagina hace POST /auth con el UID.
  4. Este servicio busca el UID en users.json -> {usuario, password}.
  5. Hace el login contra Nextcloud por detras (handshake con requesttoken).
  6. Reenvia las cookies de sesion al navegador (mismo host) y redirige a Archivos.

El password NUNCA llega al navegador.

NOTA: para el TEST usamos la contrasena real del usuario en users.json. En
produccion se sustituye por una "app password" (token revocable) de Nextcloud.
"""
import json
import os
import re
from pathlib import Path

import requests
from flask import Flask, jsonify, make_response, render_template, request

app = Flask(__name__)

# URL INTERNA de Nextcloud para el login server-side (evita el rodeo por internet).
# Test/prod: http://192.168.1.50:8181  (192.168.1.50 debe estar en trusted_domains)
NEXTCLOUD_URL = os.environ.get("NEXTCLOUD_URL", "http://192.168.1.50:8181")

# URL PUBLICA a la que se redirige el navegador tras el login.
# Test local: igual que la interna | Produccion: https://app.lanube.uno
NEXTCLOUD_PUBLIC_URL = os.environ.get("NEXTCLOUD_PUBLIC_URL", NEXTCLOUD_URL)

# Dominio para las cookies de sesion. Vacio = host-only (test local).
# Produccion con subdominios: ".lanube.uno" (se comparte entre kiosko y nextcloud).
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN") or None

# Cookies Secure solo si el navegador entra por HTTPS.
COOKIE_SECURE = NEXTCLOUD_PUBLIC_URL.startswith("https")

USERS_FILE = Path(__file__).parent / "users.json"

# Regex para extraer el requesttoken del HTML de login de Nextcloud.
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
        # Tarjeta no registrada: devolvemos el UID para poder darlo de alta.
        return jsonify(ok=False, error="Tarjeta no registrada", uid=uid), 404

    username = record["user"]
    password = record["password"]

    # Hablamos con Nextcloud por su URL (en produccion, la publica https://app...)
    # igual que un navegador real -> contexto coherente, sin lios de proxy.
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

    print(f"[AUTH] requesttoken={token[:12]}... user={username}", flush=True)

    data = {
        "user": username,
        "password": password,
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

    # Si el login falla, Nextcloud redirige de vuelta a /login.
    if "/login" in location or resp.status_code not in (301, 302, 303):
        print(f"[AUTH] RECHAZADO para user={username}", flush=True)
        return jsonify(ok=False, error="Credenciales rechazadas por Nextcloud"), 401

    print(f"[AUTH] OK login user={username} -> {location}", flush=True)

    # Login OK -> reenviamos las cookies de sesion al navegador.
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
    return jsonify(ok=True, users=len(load_users()), nextcloud=NEXTCLOUD_URL,
                   public=NEXTCLOUD_PUBLIC_URL, cookie_domain=COOKIE_DOMAIN)


@app.route("/sw.js")
def sw_js():
    """
    Service worker auto-destructor.

    Cuando el browser de una pantalla tiene un SW viejo de Nextcloud registrado
    en el scope "/" de lanube.uno, este SW intercepta todas las requests y sirve
    el contenido cacheado de Nextcloud (redirigiendo a /index.php/login).

    Este SW destructor:
      1. Se instala inmediatamente (skipWaiting) y borra todos los caches.
      2. Al activarse, toma el control de todos los clientes (claim).
      3. Se auto-desregistra para no ocupar el scope de forma permanente.
      4. Recarga todos los clientes abiertos -> el kiosko carga limpio.

    Uso: registrarlo desde /reset o manualmente:
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
    """
    js = """\
// Auto-destructor SW - La Nube kiosko NFC
// Toma el control inmediatamente, elimina todos los caches y se auto-desregistra.
self.addEventListener('install', (e) => {
    self.skipWaiting();
    e.waitUntil(
        caches.keys().then(ks => Promise.all(ks.map(k => caches.delete(k))))
    );
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        self.clients.claim()
            .then(() => self.registration.unregister())
            .then(() => self.clients.matchAll({ type: 'window' }))
            .then(cs => cs.forEach(c => c.navigate(c.url)))
    );
});

// Passthrough puro: no cachea nada mientras esta activo
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
    Pagina de limpieza para pantallas atascadas por un SW viejo de Nextcloud.

    Por que falla Clear-Site-Data solo:
      El header 'Clear-Site-Data: "cache", "storage"' borra la Cache API y el
      localStorage, pero NO desregistra service workers (no existe esa opcion
      en la spec actual). Por eso el SW fantasma sobrevive y sigue redirigiendo.

    Solucion en dos capas:
      1. JS en la pagina: llama a navigator.serviceWorker.getRegistrations() y
         desregistra todos los SWs activos o en espera.
      2. SW destructor (/sw.js): se registra como respaldo por si habia un SW
         en estado "waiting" que no aparecia en getRegistrations. Al activarse
         se auto-elimina y recarga la pagina.

    Como usar en una pantalla sin teclado:
      Escribir  lanube.uno/reset  en la barra de direcciones del browser
      (la mayoria de pantallas tactiles tienen teclado virtual).
    """
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reparando pantalla…</title>
</head>
<body style="background:#0a2540;color:#fff;font-family:sans-serif;text-align:center;padding-top:25vh">
  <h1>\U0001f9f9 Limpiando pantalla…</h1>
  <p id="st" style="opacity:.8;font-size:1.2rem">Iniciando limpieza…</p>
<script>
(async () => {
  const st = document.getElementById('st');
  const log = [];

  // 1. Desregistrar todos los service workers
  if ('serviceWorker' in navigator) {
    try {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map(r => r.unregister()));
      log.push('SW eliminados: ' + regs.length);
    } catch (e) { log.push('SW error: ' + e.message); }
  } else {
    log.push('SW: no disponible en este browser');
  }

  // 2. Limpiar todos los caches de la Cache API
  if (window.caches) {
    try {
      const keys = await caches.keys();
      await Promise.all(keys.map(k => caches.delete(k)));
      log.push('Caches: ' + keys.length + ' eliminados');
    } catch (e) { log.push('Cache error: ' + e.message); }
  }

  // 3. Limpiar almacenamiento local
  try { localStorage.clear(); sessionStorage.clear(); log.push('Storage OK'); } catch (e) {}

  // 4. Registrar el SW destructor como segunda capa de limpieza.
  //    Cubre el caso de un SW en estado "waiting" que no aparece en getRegistrations.
  if ('serviceWorker' in navigator) {
    try {
      await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      // Darle ~1 s para que se instale y active (skipWaiting + claim).
      await new Promise(r => setTimeout(r, 1000));
      log.push('SW destructor: activado');
    } catch (e) { log.push('SW destructor: ' + e.message); }
  }

  st.textContent = log.join(' · ');
  setTimeout(() => { window.location.replace('/'); }, 1500);
})();
</script>
</body>
</html>"""
    resp = make_response(html)
    # Clear-Site-Data: refuerzo adicional en browsers que lo implementan bien.
    # No desregistra SWs (no existe esa opcion), pero ayuda con caches HTTP y cookies.
    resp.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
