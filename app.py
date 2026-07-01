"""
Kiosko NFC -> Nextcloud (lanube.uno)
"""
import json
import os
import re
import secrets
import threading
import xml.etree.ElementTree as ET
from functools import wraps
from pathlib import Path

import requests
from flask import (
    Flask, jsonify, make_response, redirect,
    render_template, request, url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

VERSION              = "16"
NEXTCLOUD_URL        = os.environ.get("NEXTCLOUD_URL", "http://192.168.1.50:8181")
NEXTCLOUD_PUBLIC_URL = os.environ.get("NEXTCLOUD_PUBLIC_URL", NEXTCLOUD_URL)
COOKIE_DOMAIN        = os.environ.get("COOKIE_DOMAIN") or None
COOKIE_SECURE        = NEXTCLOUD_PUBLIC_URL.startswith("https")
ADMIN_PASSWORD       = os.environ.get("ADMIN_PASSWORD", "admin1234")

_ADMIN_SESSION = secrets.token_hex(32)

app.jinja_env.globals["version"] = VERSION

USERS_FILE = Path(__file__).parent / "users.json"

REQUESTTOKEN_RE = re.compile(r'name="requesttoken"\s+value="([^"]+)"')
HEAD_TOKEN_RE   = re.compile(r'data-requesttoken="([^"]+)"')

_CLEANUP_JS = """\
(async()=>{
  const st=document.getElementById('st');
  const go=()=>window.location.replace('/');
  const bail=setTimeout(go,5000);
  if('serviceWorker' in navigator){
    try{const r=await navigator.serviceWorker.getRegistrations();
      await Promise.all(r.map(x=>x.unregister()));}
    catch(e){}
  }
  if(window.caches){try{const k=await caches.keys();
    await Promise.all(k.map(x=>caches.delete(x)));}
    catch(e){}}
  try{localStorage.clear();sessionStorage.clear();}catch(e){}
  clearTimeout(bail);
  if(st) st.textContent='Listo, redirigiendo...';
  setTimeout(go,1000);
})();
"""

# ---------------------------------------------------------------------------
# users.json — cache por mtime, escritura con lock
# ---------------------------------------------------------------------------

_users_lock  = threading.Lock()
_users_cache = None
_users_mtime = 0.0


def load_users():
    global _users_cache, _users_mtime
    with _users_lock:
        if USERS_FILE.exists():
            mtime = USERS_FILE.stat().st_mtime
            if _users_cache is None or mtime > _users_mtime:
                _users_cache = json.loads(USERS_FILE.read_text(encoding="utf-8"))
                _users_mtime = mtime
            return dict(_users_cache)
        return {}


def save_users(users):
    global _users_cache, _users_mtime
    with _users_lock:
        USERS_FILE.write_text(
            json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _users_cache = dict(users)
        _users_mtime = USERS_FILE.stat().st_mtime


def canon_uid(raw):
    """
    Normaliza cualquier UID a HEX canónico en MAYÚSCULAS, venga de donde venga:
      - decimal de lectora (Windows / panel droidlogic): "3886968074" -> "E7AE6D0A"
      - hex (Web NFC):                                    "e7ae6d0a"   -> "E7AE6D0A"
      - hex con separadores:                              "E7:AE:6D:0A"-> "E7AE6D0A"
    Un string de solo dígitos se interpreta como el ENTERO de la lectora.
    """
    s = re.sub(r"[^0-9A-Fa-f]", "", str(raw or "")).upper()
    if not s:
        return ""
    if s.isdigit():              # solo dígitos -> valor decimal -> hex
        s = format(int(s), "X")
    if len(s) % 2:               # completar a bytes enteros
        s = "0" + s
    return s.rjust(8, "0")       # mínimo 4 bytes (8 hex)


def find_user(uid):
    """Busca el registro por UID sin importar el formato. Devuelve (clave, registro)."""
    users = load_users()
    rec = users.get(uid)
    if rec:
        return uid, rec
    target = canon_uid(uid)
    if target:
        for k, v in users.items():
            if canon_uid(k) == target:
                return k, v
    return None, None


# ---------------------------------------------------------------------------

def get_requesttoken(html):
    m = REQUESTTOKEN_RE.search(html) or HEAD_TOKEN_RE.search(html)
    return m.group(1) if m else None


def _get_app_token(username, nc_password):
    try:
        r = requests.get(
            f"{NEXTCLOUD_URL}/ocs/v2.php/core/getapppassword",
            auth=(username, nc_password),
            headers={"OCS-APIRequest": "true"},
            timeout=10,
        )
    except requests.RequestException as exc:
        return None, f"Error de red: {exc}"
    try:
        root       = ET.fromstring(r.text)
        statuscode = root.findtext(".//statuscode") or ""
        app_pw_el  = root.find(".//apppassword")
    except ET.ParseError:
        return None, "Respuesta inesperada de Nextcloud"
    if statuscode != "200" or app_pw_el is None:
        return None, root.findtext(".//message") or "Credenciales incorrectas"
    return app_pw_el.text, None


def _nc_login(username, password):
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (kiosk)"})
    try:
        login_page = s.get(f"{NEXTCLOUD_URL}/login", timeout=15)
    except requests.RequestException as exc:
        return None, f"No se pudo contactar Nextcloud: {exc}"
    token = get_requesttoken(login_page.text)
    if not token:
        return None, "Error interno al obtener requesttoken"
    resp = s.post(
        f"{NEXTCLOUD_URL}/login",
        data={
            "user": username, "password": password,
            "requesttoken": token, "timezone": "America/Lima",
            "timezone_offset": "-5", "rememberme": "true",
        },
        headers={"requesttoken": token, "Origin": NEXTCLOUD_PUBLIC_URL,
                 "Referer": f"{NEXTCLOUD_PUBLIC_URL}/login"},
        allow_redirects=False, timeout=10,
    )
    location = resp.headers.get("Location", "")
    if "/login" in location or resp.status_code not in (301, 302, 303):
        return None, "Usuario o contraseña incorrectos"
    return s, None


def _nc_change_password(username, old_password, new_password):
    try:
        r = requests.put(
            f"{NEXTCLOUD_URL}/ocs/v1.php/cloud/users/{username}",
            auth=(username, old_password),
            headers={"OCS-APIRequest": "true"},
            data={"key": "password", "value": new_password},
            timeout=10,
        )
    except requests.RequestException as exc:
        return False, f"Error de red: {exc}"
    try:
        root       = ET.fromstring(r.text)
        statuscode = root.findtext(".//statuscode") or ""
    except ET.ParseError:
        return False, "Respuesta inesperada de Nextcloud"
    if statuscode in ("100", "200"):
        return True, None
    return False, root.findtext(".//message") or f"Error {statuscode}"


def _nc_session_from_token(username, app_token):
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (kiosk)",
                      "Accept": "text/html,application/xhtml+xml,*/*"})
    try:
        r = s.get(f"{NEXTCLOUD_URL}/apps/files",
                  auth=(username, app_token), allow_redirects=True, timeout=15)
    except requests.RequestException as exc:
        return None, f"No se pudo contactar Nextcloud: {exc}"
    if r.status_code != 200 or "/login" in r.url:
        return None, "Credenciales rechazadas por Nextcloud"
    return s, None


def _apply_nc_cookies(out_resp, nc_session):
    for c in nc_session.cookies:
        if c.name.startswith("__Host-"):
            continue
        out_resp.set_cookie(c.name, c.value, path="/", httponly=True,
                            samesite="Lax", domain=COOKIE_DOMAIN,
                            secure=COOKIE_SECURE)


def _cleanup_page(title, subtitle):
    html = f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Segoe UI", system-ui, sans-serif; background: #f0f2f4; color: #0f172a;
    display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 2.75rem 2.5rem 2.25rem; width: 90%; max-width: 380px; text-align: center;
    box-shadow: 0 1px 2px rgba(0,0,0,.05), 0 4px 20px rgba(0,0,0,.06); }}
  .logo-mark {{ width: 44px; height: 44px; background: #0f172a; border-radius: 10px;
    display: inline-flex; align-items: center; justify-content: center; margin-bottom: 1.25rem; }}
  h1 {{ font-size: 1.3rem; font-weight: 700; color: #0f172a; margin-bottom: .3rem; }}
  .sub {{ font-size: .875rem; color: #64748b; margin-bottom: 1.75rem; }}
  #st {{ font-size: .85rem; color: #64748b; min-height: 1.2rem; margin-bottom: 1.5rem; }}
  .btn {{ display: inline-block; padding: .7rem 2rem; background: #0f172a; color: #fff;
    border: none; border-radius: 8px; font-size: .95rem; font-weight: 600;
    text-decoration: none; transition: background .15s; }}
  .btn:hover {{ background: #1e293b; }}
  .ver {{ position: fixed; bottom: .5rem; right: .75rem;
    font-size: .6rem; color: #d1d5db; pointer-events: none; }}
</style>
</head>
<body>
  <div class="card">
    <div class="logo-mark">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
           stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9z"/>
      </svg>
    </div>
    <h1>{title}</h1>
    <p class="sub">{subtitle}</p>
    <p id="st"></p>
    <a href="/" id="btn" class="btn"
       onclick="document.getElementById('btn').style.opacity='.5'">
      Ir al inicio de sesión
    </a>
  </div>
  <span class="ver">v{VERSION}</span>
  <script>{_CLEANUP_JS}</script>
</body></html>"""
    resp = make_response(html)
    resp.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


# ---------------------------------------------------------------------------
# Admin auth
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
            resp.set_cookie("admin_session", _ADMIN_SESSION,
                            httponly=True, samesite="Lax",
                            secure=COOKIE_SECURE, max_age=28800)
            return resp
        error = "Contraseña incorrecta"
    return render_template("admin.html", authenticated=False, error=error)


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
    return render_template("index.html", nextcloud_url=NEXTCLOUD_PUBLIC_URL,
                           auto_repair=False)


@app.route("/auth", methods=["POST"])
@limiter.limit("30 per minute",
               error_message="Demasiados intentos. Esperá un momento.")
def auth():
    uid = (request.form.get("uid") or "").strip()
    if not uid:
        return jsonify(ok=False, error="UID vacio"), 400

    _, record = find_user(uid)
    if not record:
        return jsonify(ok=False, error="Tarjeta no registrada", uid=uid), 404

    username  = record["user"]
    app_token = record.get("token")

    if not app_token:
        return jsonify(ok=False,
                       error="Sin token configurado. Registrá la tarjeta de nuevo."), 500

    print(f"[AUTH] user={username}", flush=True)
    s, err = _nc_session_from_token(username, app_token)
    if err:
        print(f"[AUTH] RECHAZADO user={username}: {err}", flush=True)
        return jsonify(ok=False, error=err), 401

    print(f"[AUTH] OK user={username}", flush=True)
    out = make_response(jsonify(
        ok=True,
        redirect=f"{NEXTCLOUD_PUBLIC_URL}/apps/files",
        user=username,
    ))
    for name in list(request.cookies.keys()):
        if not name.startswith("admin_"):
            out.delete_cookie(name, path="/")
            out.delete_cookie(name, path="/app")
    _apply_nc_cookies(out, s)
    return out


@app.route("/login-manual", methods=["GET"])
def login_manual():
    error   = request.args.get("error", "")
    prefill = request.args.get("user", "")
    return render_template("login_manual.html", error=error, prefill=prefill)


@app.route("/auth-form", methods=["POST"])
@limiter.limit("10 per 5 minutes",
               error_message="Demasiados intentos. Esperá 5 minutos.")
def auth_form():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()

    if not username or not password:
        return redirect(url_for("login_manual",
                                error="Ingresá usuario y contraseña",
                                user=username))

    print(f"[AUTH-FORM] user={username}", flush=True)
    app_token, err = _get_app_token(username, password)
    if err:
        print(f"[AUTH-FORM] OCS RECHAZADO user={username}: {err}", flush=True)
        return redirect(url_for("login_manual",
                                error="Usuario o contraseña incorrectos",
                                user=username))

    s, err = _nc_session_from_token(username, app_token)
    if err:
        print(f"[AUTH-FORM] SESSION ERROR user={username}: {err}", flush=True)
        return redirect(url_for("login_manual",
                                error="Error al iniciar sesión. Intentá de nuevo.",
                                user=username))

    print(f"[AUTH-FORM] OK user={username}", flush=True)
    out = make_response(redirect(f"{NEXTCLOUD_PUBLIC_URL}/apps/files"))
    for name in list(request.cookies.keys()):
        if not name.startswith("admin_"):
            out.delete_cookie(name, path="/")
            out.delete_cookie(name, path="/app")
    _apply_nc_cookies(out, s)
    return out


@app.route("/health")
def health():
    users = load_users()
    return jsonify(
        ok=True, version=VERSION,
        users=len(users),
        con_token=sum(1 for v in users.values() if v.get("token")),
        con_password=sum(1 for v in users.values()
                         if v.get("password") and not v.get("token")),
        nextcloud=NEXTCLOUD_URL, public=NEXTCLOUD_PUBLIC_URL,
        cookie_domain=COOKIE_DOMAIN,
    )


@app.route("/login")
def login_catch():
    return render_template("index.html", nextcloud_url=NEXTCLOUD_PUBLIC_URL,
                           auto_repair=True)


@app.route("/index.php", defaults={"subpath": ""})
@app.route("/index.php/<path:subpath>")
def nextcloud_catch(subpath):
    return render_template("index.html", nextcloud_url=NEXTCLOUD_PUBLIC_URL,
                           auto_repair=True)


# ---------------------------------------------------------------------------
# Service workers
# ---------------------------------------------------------------------------

@app.route("/sw-kiosk.js")
def sw_kiosk_js():
    js = """\
// Kiosko SW permanente - La Nube NFC
let _kioskExpires = 0;
self.addEventListener('install', (e) => {
    self.skipWaiting();
    e.waitUntil(caches.keys().then(ks => Promise.all(ks.map(k => caches.delete(k)))));
});
self.addEventListener('activate', (e) => { e.waitUntil(self.clients.claim()); });
self.addEventListener('message', (e) => {
    if (e.data && e.data.type === 'KIOSK_SESSION') {
        _kioskExpires = e.data.expiresAt || 0;
    }
});
self.addEventListener('fetch', (e) => {
    if (e.request.mode === 'navigate' && _kioskExpires && Date.now() > _kioskExpires) {
        e.respondWith(Response.redirect('/', 302));
        return;
    }
    e.respondWith(fetch(e.request));
});
"""
    resp = make_response(js)
    resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-store, no-cache"
    return resp


@app.route("/sw.js")
def sw_js():
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


@app.route("/logout")
def nc_logout():
    requesttoken = request.args.get("requesttoken", "")
    if requesttoken:
        try:
            nc_cookies = {k: v for k, v in request.cookies.items()
                          if not k.startswith("admin_")}
            requests.get(f"{NEXTCLOUD_URL}/logout",
                         params={"requesttoken": requesttoken},
                         cookies=nc_cookies, allow_redirects=False, timeout=5)
        except Exception:
            pass
    resp = make_response(redirect("/"))
    for name in list(request.cookies.keys()):
        if not name.startswith("admin_"):
            resp.delete_cookie(name, path="/")
    print("[LOGOUT] Sesión cerrada, volviendo al kiosko", flush=True)
    return resp


@app.route("/reset")
def reset():
    return _cleanup_page(title="Reparando pantalla…",
                         subtitle="Limpiando caché y service workers…")


@app.route("/uid-lookup")
def uid_lookup():
    uid = (request.args.get("uid") or "").strip()
    if not uid:
        return jsonify(ok=False), 400
    _, record = find_user(uid)
    if not record:
        return jsonify(ok=False, error="Tarjeta no registrada"), 404
    return jsonify(ok=True, user=record["user"], name=record.get("name", record["user"]))


@app.route("/cambiar-clave", methods=["GET", "POST"])
@limiter.limit("5 per 10 minutes", methods=["POST"],
               error_message="Demasiados intentos. Esperá 10 minutos.")
def cambiar_clave():
    if request.method == "GET":
        uid = request.args.get("uid", "")
        prefill_user = ""
        display_name = ""
        if uid:
            record = load_users().get(uid)
            if record:
                prefill_user = record["user"]
                display_name = record.get("name", record["user"])
        return render_template("cambiar_clave.html", prefill_user=prefill_user,
                               display_name=display_name, error="", success=False)

    username = (request.form.get("username")     or "").strip()
    old_pass = (request.form.get("old_password") or "").strip()
    new_pass = (request.form.get("new_password") or "").strip()
    confirm  = (request.form.get("confirm")      or "").strip()

    def bad(msg):
        return render_template("cambiar_clave.html", prefill_user=username,
                               display_name="", error=msg, success=False)

    if not username or not old_pass or not new_pass:
        return bad("Completá todos los campos.")
    if new_pass != confirm:
        return bad("Las contraseñas nuevas no coinciden.")
    if len(new_pass) < 8:
        return bad("La contraseña nueva debe tener al menos 8 caracteres.")

    ok, err = _nc_change_password(username, old_pass, new_pass)
    if not ok:
        return bad("Usuario o contraseña incorrectos.")

    token, err = _get_app_token(username, new_pass)
    if err:
        print(f"[CAMBIAR-CLAVE] Contraseña OK pero error token user={username}: {err}",
              flush=True)
        return bad("Contraseña cambiada, pero error al actualizar la tarjeta NFC. Avisá al admin.")

    users = load_users()
    for record in users.values():
        if record.get("user") == username:
            record["token"] = token
            record.pop("password", None)
            break
    save_users(users)
    print(f"[CAMBIAR-CLAVE] OK user={username}", flush=True)
    return render_template("cambiar_clave.html", prefill_user="", display_name="",
                           error="", success=True, changed_user=username)


# ---------------------------------------------------------------------------
# Panel admin
# ---------------------------------------------------------------------------

@app.route("/admin")
@require_admin
def admin_panel():
    return render_template("admin.html", authenticated=True,
                           users=load_users(), nextcloud_url=NEXTCLOUD_PUBLIC_URL)


@app.route("/admin/register", methods=["POST"])
@require_admin
def admin_register():
    uid         = (request.form.get("uid")         or "").strip()
    username    = (request.form.get("username")    or "").strip()
    nc_password = (request.form.get("nc_password") or "").strip()
    if not uid or not username or not nc_password:
        return jsonify(ok=False, error="Faltan campos"), 400
    token, err = _get_app_token(username, nc_password)
    if err:
        return jsonify(ok=False, error=err), 401
    canon = canon_uid(uid)
    users = load_users()
    # quitar cualquier entrada previa de la misma tarjeta (otro formato) para no duplicar
    for k in [k for k in users if canon_uid(k) == canon]:
        users.pop(k, None)
    users[canon] = {"user": username, "name": username, "token": token}
    save_users(users)
    print(f"[ADMIN] Registrada: uid={canon} user={username}", flush=True)
    return jsonify(ok=True, uid=canon, user=username, name=username)


@app.route("/admin/update", methods=["POST"])
@require_admin
def admin_update():
    uid          = (request.form.get("uid")          or "").strip()
    display_name = (request.form.get("display_name") or "").strip()
    nc_password  = (request.form.get("nc_password")  or "").strip()
    users = load_users()
    if uid not in users:
        return jsonify(ok=False, error="UID no encontrado"), 404
    record   = users[uid]
    username = record["user"]
    if display_name:
        record["name"] = display_name
    if nc_password:
        token, err = _get_app_token(username, nc_password)
        if err:
            return jsonify(ok=False, error=err), 401
        record["token"] = token
        record.pop("password", None)
    save_users(users)
    print(f"[ADMIN] Actualizada: uid={uid} user={username}", flush=True)
    return jsonify(ok=True, uid=uid, name=record.get("name", username),
                   has_token=bool(record.get("token")))


@app.route("/admin/bulk", methods=["POST"])
@require_admin
def admin_bulk():
    csv_data = (request.form.get("csv_data") or "").strip()
    if not csv_data:
        return jsonify(ok=False, error="CSV vacio"), 400
    users   = load_users()
    results = []
    for raw in csv_data.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.lower().startswith("uid"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            results.append({"line": line, "ok": False,
                            "error": "Formato inválido (necesita uid,usuario,contraseña)"})
            continue
        uid, username, nc_password = parts[0], parts[1], parts[2]
        display_name = parts[3] if len(parts) > 3 else username
        if not uid or not username or not nc_password:
            results.append({"uid": uid, "user": username, "ok": False, "error": "Campo vacío"})
            continue
        token, err = _get_app_token(username, nc_password)
        if err:
            results.append({"uid": uid, "user": username, "ok": False, "error": err})
        else:
            canon = canon_uid(uid)
            for k in [k for k in users if canon_uid(k) == canon]:
                users.pop(k, None)
            users[canon] = {"user": username, "name": display_name, "token": token}
            results.append({"uid": canon, "user": username, "name": display_name, "ok": True})
            print(f"[BULK] uid={canon} user={username}", flush=True)
    save_users(users)
    ok_count = sum(1 for r in results if r["ok"])
    return jsonify(ok=True, total=len(results), registered=ok_count, results=results)


@app.route("/admin/create-nc-users", methods=["POST"])
@require_admin
def admin_create_nc_users():
    nc_admin_user = (request.form.get("nc_admin_user") or "").strip()
    nc_admin_pass = (request.form.get("nc_admin_pass") or "").strip()
    csv_data      = (request.form.get("nc_csv")        or "").strip()
    if not nc_admin_user or not nc_admin_pass or not csv_data:
        return jsonify(ok=False, error="Faltan campos"), 400
    results = []
    for raw in csv_data.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.lower().startswith("usuario"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            results.append({"line": line, "ok": False, "error": "Formato inválido"})
            continue
        username, nc_password = parts[0], parts[1]
        display_name = parts[2] if len(parts) > 2 else username
        email        = parts[3] if len(parts) > 3 else ""
        if not username or not nc_password:
            results.append({"user": username, "ok": False, "error": "Campo vacío"})
            continue
        data = {"userid": username, "password": nc_password, "displayName": display_name}
        if email:
            data["email"] = email
        try:
            r = requests.post(f"{NEXTCLOUD_URL}/ocs/v1.php/cloud/users",
                              auth=(nc_admin_user, nc_admin_pass),
                              headers={"OCS-APIRequest": "true"}, data=data, timeout=15)
            root       = ET.fromstring(r.text)
            statuscode = root.findtext(".//statuscode") or ""
            if statuscode in ("100", "200"):
                results.append({"user": username, "ok": True})
                print(f"[NC-CREATE] user={username}", flush=True)
            elif statuscode == "102":
                results.append({"user": username, "ok": False, "error": "Usuario ya existe"})
            else:
                msg = root.findtext(".//message") or f"Error {statuscode}"
                results.append({"user": username, "ok": False, "error": msg})
        except requests.RequestException as exc:
            results.append({"user": username, "ok": False, "error": f"Red: {exc}"})
        except ET.ParseError:
            results.append({"user": username, "ok": False, "error": "Respuesta inesperada"})
    ok_count = sum(1 for r in results if r["ok"])
    return jsonify(ok=True, total=len(results), created=ok_count, results=results)


@app.route("/admin/nc-users")
@require_admin
def admin_nc_users():
    nc_admin_user = request.args.get("nc_admin_user", "").strip()
    nc_admin_pass = request.args.get("nc_admin_pass", "").strip()
    if not nc_admin_user or not nc_admin_pass:
        return jsonify(ok=False, error="Faltan credenciales de admin NC"), 400
    try:
        r = requests.get(f"{NEXTCLOUD_URL}/ocs/v1.php/cloud/users",
                         auth=(nc_admin_user, nc_admin_pass),
                         headers={"OCS-APIRequest": "true"}, timeout=15)
        root       = ET.fromstring(r.text)
        statuscode = root.findtext(".//statuscode") or ""
        if statuscode not in ("100", "200"):
            return jsonify(ok=False,
                           error=root.findtext(".//message") or "Acceso denegado"), 401
        nc_users = [el.text for el in root.findall(".//users/element") if el.text]
    except requests.RequestException as exc:
        return jsonify(ok=False, error=f"Error de red: {exc}"), 502
    except ET.ParseError:
        return jsonify(ok=False, error="Respuesta inesperada de Nextcloud"), 502
    local_users = load_users()
    by_username = {}
    for uid, info in local_users.items():
        u = info.get("user", "")
        if u:
            by_username[u] = {"uid": uid, "has_token": bool(info.get("token")),
                              "name": info.get("name", u)}
    result = [{"username": u, "card": by_username.get(u)}
              for u in sorted(nc_users, key=str.lower)]
    return jsonify(ok=True, users=result, total=len(result))


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
