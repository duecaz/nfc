"""
Kiosko NFC -> Nextcloud (lanube.uno)
-------------------------------------
Mini-servicio que loguea a un docente en Nextcloud usando solo el UID de su
tarjeta NFC (el lector USB "teclea" el UID como un teclado).

Flujo:
  1. El navegador (pantalla) muestra la pagina kiosko con un campo enfocado.
  2. El docente pasa la tarjeta -> el lector escribe el UID + Enter.
  3. La pagina hace POST /auth con el UID.
  4. Este servicio busca el UID en users.json -> {usuario, token}.
  5. Hace el login contra Nextcloud por detras (handshake con requesttoken).
  6. Reenvia las cookies de sesion al navegador (mismo host) y redirige a Archivos.

El token NUNCA llega al navegador.

Rutas:
  GET  /          -> kiosko NFC (pantallas interactivas)
  POST /auth      -> autenticacion via UID
  GET  /health    -> estado del servicio
  GET  /sw.js     -> SW auto-destructor (limpia SWs viejos de Nextcloud)
  GET  /reset     -> limpieza de pantalla atascada (sin F12 ni DevTools)
  GET  /admin     -> panel de administracion (HTTP Basic Auth)
  POST /admin/register -> registrar tarjeta + generar token NC
  POST /admin/delete   -> eliminar tarjeta
"""
import json
import os
import re
import xml.etree.ElementTree as ET
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, jsonify, make_response, render_template, request

app = Flask(__name__)

NEXTCLOUD_URL = os.environ.get("NEXTCLOUD_URL", "http://192.168.1.50:8181")
NEXTCLOUD_PUBLIC_URL = os.environ.get("NEXTCLOUD_PUBLIC_URL", NEXTCLOUD_URL)
COOKIE_DOMAIN = os.environ.get("COOKIE_DOMAIN") or None
COOKIE_SECURE = NEXTCLOUD_PUBLIC_URL.startswith("https")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")

USERS_FILE = Path(__file__).parent / "users.json"

REQUESTTOKEN_RE = re.compile(r'name="requesttoken"\s+value="([^"]+)"')
HEAD_TOKEN_RE = re.compile(r'data-requesttoken="([^"]+)"')


def load_users():
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {}


def save_users(users):
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def get_requesttoken(html):
    m = REQUESTTOKEN_RE.search(html) or HEAD_TOKEN_RE.search(html)
    return m.group(1) if m else None


def require_admin(f):
    """Decorator: exige HTTP Basic Auth con usuario 'admin' y ADMIN_PASSWORD."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != "admin" or auth.password != ADMIN_PASSWORD:
            return make_response(
                "<h1>Acceso denegado</h1>", 401,
                {"WWW-Authenticate": 'Basic realm="Admin La Nube"'}
            )
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Kiosko
# ---------------------------------------------------------------------------

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
    # Preferir token (app password revocable) sobre contrasena real.
    credential = record.get("token") or record.get("password")
    using_token = bool(record.get("token"))

    if not credential:
        return jsonify(ok=False, error="Sin credencial configurada"), 500

    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (kiosk)"})
    try:
        login_page = s.get(f"{NEXTCLOUD_URL}/login", timeout=15)
    except requests.RequestException as exc:
        print(f"[AUTH] ERROR contacto NC: {exc}", flush=True)
        return jsonify(ok=False, error=f"No se pudo contactar Nextcloud: {exc}"), 502

    token = get_requesttoken(login_page.text)
    if not token:
        print("[AUTH] ERROR: no se encontro requesttoken", flush=True)
        return jsonify(ok=False, error="No se obtuvo requesttoken"), 502

    cred_type = "token" if using_token else "password"
    print(f"[AUTH] user={username} cred={cred_type} requesttoken={token[:12]}...",
          flush=True)

    resp = s.post(
        f"{NEXTCLOUD_URL}/login",
        data={
            "user": username,
            "password": credential,
            "requesttoken": token,
            "timezone": "America/Lima",
            "timezone_offset": "-5",
            "rememberme": "true",
        },
        headers={
            "requesttoken": token,
            "Origin": NEXTCLOUD_PUBLIC_URL,
            "Referer": f"{NEXTCLOUD_PUBLIC_URL}/login",
        },
        allow_redirects=False,
        timeout=10,
    )

    location = resp.headers.get("Location", "")
    print(f"[AUTH] POST /login -> {resp.status_code} location={location!r}",
          flush=True)

    if "/login" in location or resp.status_code not in (301, 302, 303):
        print(f"[AUTH] RECHAZADO user={username} cred={cred_type}", flush=True)
        return jsonify(ok=False, error="Credenciales rechazadas por Nextcloud"), 401

    print(f"[AUTH] OK user={username}", flush=True)

    out = make_response(jsonify(
        ok=True,
        redirect=f"{NEXTCLOUD_PUBLIC_URL}/apps/files",
        user=username,
    ))
    for c in s.cookies:
        if COOKIE_DOMAIN and c.name.startswith("__Host-"):
            continue
        out.set_cookie(c.name, c.value, path="/", httponly=True, samesite="Lax",
                       domain=COOKIE_DOMAIN, secure=COOKIE_SECURE)
    return out


@app.route("/health")
def health():
    users = load_users()
    token_count = sum(1 for v in users.values() if v.get("token"))
    pass_count = sum(1 for v in users.values()
                     if v.get("password") and not v.get("token"))
    return jsonify(
        ok=True,
        users=len(users),
        con_token=token_count,
        con_password=pass_count,
        nextcloud=NEXTCLOUD_URL,
        public=NEXTCLOUD_PUBLIC_URL,
        cookie_domain=COOKIE_DOMAIN,
    )


# ---------------------------------------------------------------------------
# Service worker y reset
# ---------------------------------------------------------------------------

@app.route("/sw.js")
def sw_js():
    """SW auto-destructor: toma control, borra caches y se desregistra sin
    navegar clientes (evita el bucle /reset -> /reset)."""
    js = """\
// Auto-destructor SW - La Nube kiosko NFC
self.addEventListener('install', (e) => {
    self.skipWaiting();
    e.waitUntil(caches.keys().then(ks => Promise.all(ks.map(k => caches.delete(k)))));
});
self.addEventListener('activate', (e) => {
    e.waitUntil(self.clients.claim().then(() => self.registration.unregister()));
});
self.addEventListener('fetch', (e) => { e.respondWith(fetch(e.request)); });
"""
    resp = make_response(js)
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-store, no-cache"
    return resp


@app.route("/reset")
def reset():
    """Limpieza para pantallas atascadas por SW fantasma de Nextcloud.
    Acceder escribiendo  lanube.uno/reset  en la barra de URLs (teclado virtual).
    NO requiere F12 ni DevTools.
    """
    html = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reparando…</title>
</head>
<body style="background:#0a2540;color:#fff;font-family:sans-serif;
            text-align:center;padding-top:20vh;padding:20vh 1rem 0">
<h1>&#x1F9F9; Limpiando pantalla…</h1>
<p id="st" style="opacity:.8;font-size:1.2rem;margin-top:1rem">Iniciando…</p>
<div id="btn" style="display:none;margin-top:2.5rem">
  <a href="/" style="display:inline-block;padding:1rem 2.5rem;background:#3ddc97;
     color:#0a2540;border-radius:12px;text-decoration:none;font-size:1.3rem;
     font-weight:700">Abrir kiosko NFC &#x2192;</a>
</div>
<script>
(async()=>{
  const st=document.getElementById('st'),btn=document.getElementById('btn'),log=[];
  if('serviceWorker' in navigator){
    try{const r=await navigator.serviceWorker.getRegistrations();
      await Promise.all(r.map(x=>x.unregister()));log.push('SW:'+r.length);}
    catch(e){log.push('SW err');}
  }
  if(window.caches){try{const k=await caches.keys();
    await Promise.all(k.map(x=>caches.delete(x)));log.push('Cache:'+k.length);}catch(e){}}
  try{localStorage.clear();sessionStorage.clear();}catch(e){}
  if('serviceWorker' in navigator){
    try{await navigator.serviceWorker.register('/sw.js',{scope:'/'});
      await new Promise(r=>setTimeout(r,1000));log.push('Destructor:OK');}
    catch(e){log.push('Destructor:'+e.message);}
  }
  st.textContent='✅ '+log.join(' · ');
  btn.style.display='block';
  setTimeout(()=>{window.location.replace('/');},2000);
})();
</script></body></html>"""
    resp = make_response(html)
    resp.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


# ---------------------------------------------------------------------------
# Panel de administracion
# ---------------------------------------------------------------------------

@app.route("/admin")
@require_admin
def admin_panel():
    return render_template("admin.html",
                           users=load_users(),
                           nextcloud_url=NEXTCLOUD_PUBLIC_URL)


@app.route("/admin/register", methods=["POST"])
@require_admin
def admin_register():
    """Genera un app password de Nextcloud para el docente y lo guarda en
    users.json junto con el UID de su tarjeta. La contrasena real del
    docente se usa una sola vez y nunca se almacena.
    """
    uid          = (request.form.get("uid")          or "").strip()
    username     = (request.form.get("username")     or "").strip()
    nc_password  = (request.form.get("nc_password")  or "").strip()
    display_name = (request.form.get("display_name") or username).strip()

    if not uid or not username or not nc_password:
        return jsonify(ok=False, error="Faltan campos: uid, username o nc_password"), 400

    # Pedir a Nextcloud que genere un app password para este usuario.
    # La autenticacion es con la clave real; el token resultante es revocable.
    try:
        r = requests.get(
            f"{NEXTCLOUD_URL}/ocs/v2.php/core/getapppassword",
            auth=(username, nc_password),
            headers={"OCS-APIRequest": "true"},
            timeout=10,
        )
    except requests.RequestException as exc:
        return jsonify(ok=False, error=f"Error contactando Nextcloud: {exc}"), 502

    try:
        root = ET.fromstring(r.text)
        statuscode = root.findtext(".//statuscode") or ""
        app_pw_el  = root.find(".//apppassword")
    except ET.ParseError:
        return jsonify(ok=False, error="Respuesta inesperada de Nextcloud"), 502

    if statuscode != "200" or app_pw_el is None:
        msg = root.findtext(".//message") or "Credenciales incorrectas"
        return jsonify(ok=False, error=msg), 401

    token = app_pw_el.text
    users = load_users()
    users[uid] = {"user": username, "name": display_name, "token": token}
    save_users(users)

    print(f"[ADMIN] Tarjeta registrada: uid={uid} user={username}", flush=True)
    return jsonify(ok=True, uid=uid, user=username, name=display_name)


@app.route("/admin/delete", methods=["POST"])
@require_admin
def admin_delete():
    uid = (request.form.get("uid") or "").strip()
    users = load_users()
    if uid not in users:
        return jsonify(ok=False, error="UID no encontrado"), 404
    removed = users.pop(uid)
    save_users(users)
    print(f"[ADMIN] Tarjeta eliminada: uid={uid} user={removed.get('user')}",
          flush=True)
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
