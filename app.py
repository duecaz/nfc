"""
Kiosko NFC -> Nextcloud (lanube.uno)
"""
import json
import os
import re
import secrets
import xml.etree.ElementTree as ET
from functools import wraps
from pathlib import Path

import requests
from flask import (
    Flask, jsonify, make_response, redirect,
    render_template, request, url_for,
)

app = Flask(__name__)

NEXTCLOUD_URL        = os.environ.get("NEXTCLOUD_URL", "http://192.168.1.50:8181")
NEXTCLOUD_PUBLIC_URL = os.environ.get("NEXTCLOUD_PUBLIC_URL", NEXTCLOUD_URL)
COOKIE_DOMAIN        = os.environ.get("COOKIE_DOMAIN") or None
COOKIE_SECURE        = NEXTCLOUD_PUBLIC_URL.startswith("https")
ADMIN_PASSWORD       = os.environ.get("ADMIN_PASSWORD", "admin1234")

# Token de sesion admin generado al arrancar.
# Si el contenedor se reinicia todas las sesiones se invalidan (comportamiento OK).
_ADMIN_SESSION = secrets.token_hex(32)

USERS_FILE = Path(__file__).parent / "users.json"

REQUESTTOKEN_RE = re.compile(r'name="requesttoken"\s+value="([^"]+)"')
HEAD_TOKEN_RE   = re.compile(r'data-requesttoken="([^"]+)"')


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


# ---------------------------------------------------------------------------
# Admin auth (formulario + cookie — funciona a traves de Cloudflare)
# ---------------------------------------------------------------------------

def is_admin():
    return request.cookies.get("admin_session") == _ADMIN_SESSION


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        pw = (request.form.get("password") or "").strip()
        if pw == ADMIN_PASSWORD:
            resp = make_response(redirect(url_for("admin_panel")))
            resp.set_cookie(
                "admin_session", _ADMIN_SESSION,
                httponly=True, samesite="Lax",
                secure=COOKIE_SECURE, max_age=28800,  # 8 horas
            )
            return resp
        error = "Contraseña incorrecta"
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    resp = make_response(redirect(url_for("admin_login")))
    resp.delete_cookie("admin_session")
    return resp


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

    username   = record["user"]
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
    print(f"[AUTH] user={username} cred={cred_type}", flush=True)

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
        print(f"[AUTH] RECHAZADO user={username}", flush=True)
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
    return jsonify(
        ok=True,
        users=len(users),
        con_token=sum(1 for v in users.values() if v.get("token")),
        con_password=sum(1 for v in users.values()
                         if v.get("password") and not v.get("token")),
        nextcloud=NEXTCLOUD_URL,
        public=NEXTCLOUD_PUBLIC_URL,
        cookie_domain=COOKIE_DOMAIN,
    )


# ---------------------------------------------------------------------------
# Service worker y reset
# ---------------------------------------------------------------------------

@app.route("/sw.js")
def sw_js():
    js = """\
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
    html = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reparando…</title></head>
<body style="background:#0a2540;color:#fff;font-family:sans-serif;
            text-align:center;padding:20vh 1rem 0">
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
      await Promise.all(r.map(x=>x.unregister()));log.push('SW:'+r.length);}catch(e){}
  }
  if(window.caches){try{const k=await caches.keys();
    await Promise.all(k.map(x=>caches.delete(x)));log.push('Cache:'+k.length);}catch(e){}}
  try{localStorage.clear();sessionStorage.clear();}catch(e){}
  if('serviceWorker' in navigator){
    try{await navigator.serviceWorker.register('/sw.js',{scope:'/'});
      await new Promise(r=>setTimeout(r,1000));log.push('Destructor:OK');}catch(e){}
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
# Panel admin
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
    uid          = (request.form.get("uid")          or "").strip()
    username     = (request.form.get("username")     or "").strip()
    nc_password  = (request.form.get("nc_password")  or "").strip()
    display_name = (request.form.get("display_name") or username).strip()

    if not uid or not username or not nc_password:
        return jsonify(ok=False, error="Faltan campos"), 400

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
        root       = ET.fromstring(r.text)
        statuscode = root.findtext(".//statuscode") or ""
        app_pw_el  = root.find(".//apppassword")
    except ET.ParseError:
        return jsonify(ok=False, error="Respuesta inesperada de Nextcloud"), 502

    if statuscode != "200" or app_pw_el is None:
        msg = root.findtext(".//message") or "Credenciales incorrectas"
        return jsonify(ok=False, error=msg), 401

    users = load_users()
    users[uid] = {"user": username, "name": display_name, "token": app_pw_el.text}
    save_users(users)

    print(f"[ADMIN] Registrada: uid={uid} user={username}", flush=True)
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
    print(f"[ADMIN] Eliminada: uid={uid} user={removed.get('user')}", flush=True)
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
