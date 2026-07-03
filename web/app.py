"""
Kiosko NFC -> Nextcloud (lanube.uno)
"""
import json
import os
import re
import secrets
import shutil
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import closing
from functools import wraps
from pathlib import Path

import requests
from datetime import datetime, timezone
from flask import (
    Flask, jsonify, make_response, redirect,
    render_template, request, url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
# Detras de nginx + Cloudflare: usar la IP real del cliente (X-Forwarded-For),
# no la del proxy. Sin esto el rate-limit y los logs ven a TODA la flota como 1 IP.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def _auth_key():
    """Rate-limit de /auth por UID de tarjeta (no por IP): así una tarjeta no se
    puede repetir en rafaga, pero NO se limita a toda la flota (que comparte IP
    publica detras del tunel)."""
    return (request.form.get("uid") or "").strip() or get_remote_address()


limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

VERSION              = "25"
NEXTCLOUD_URL        = os.environ.get("NEXTCLOUD_URL", "http://192.168.1.50:8181")
NEXTCLOUD_PUBLIC_URL = os.environ.get("NEXTCLOUD_PUBLIC_URL", NEXTCLOUD_URL)
COOKIE_DOMAIN        = os.environ.get("COOKIE_DOMAIN") or None
COOKIE_SECURE        = NEXTCLOUD_PUBLIC_URL.startswith("https")
ADMIN_PASSWORD       = os.environ.get("ADMIN_PASSWORD", "admin1234")
PANEL_SECRET         = os.environ.get("PANEL_SECRET", "")

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
# Almacenamiento SQLite (v25, F2) — transacciones ACID seguras entre procesos.
# Reemplaza users.json/panels.json; migra users.json automaticamente 1 vez.
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).parent / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FILE = DATA_DIR / "kiosk.db"


def _db():
    con = sqlite3.connect(DB_FILE, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _init_db():
    with closing(_db()) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS cards("
                    "uid TEXT PRIMARY KEY, user TEXT, name TEXT, token TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS panels("
                    "id TEXT PRIMARY KEY, apk TEXT, nfc TEXT, ip TEXT, seen TEXT, ram TEXT)")
        con.execute("CREATE TABLE IF NOT EXISTS config(k TEXT PRIMARY KEY, v TEXT)")
        # migracion unica desde users.json (si la tabla esta vacia)
        if con.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0 and USERS_FILE.exists():
            try:
                old = json.loads(USERS_FILE.read_text(encoding="utf-8"))
                rows = [(u, r.get("user", ""), r.get("name", r.get("user", "")),
                         r.get("token", "")) for u, r in old.items()
                        if not u.startswith("EJEMPLO")]
                con.executemany("INSERT OR REPLACE INTO cards VALUES(?,?,?,?)", rows)
                print(f"[DB] migradas {len(rows)} tarjetas desde users.json", flush=True)
            except Exception as exc:
                print(f"[DB] migracion users.json fallo: {exc}", flush=True)


_init_db()


def load_users():
    with closing(_db()) as con:
        rows = con.execute("SELECT uid, user, name, token FROM cards").fetchall()
    return {u: {"user": us, "name": nm, "token": tk} for u, us, nm, tk in rows}


def save_users(users):
    """Reemplaza el set completo en UNA transaccion (atomico entre procesos)."""
    with closing(_db()) as con, con:
        con.execute("DELETE FROM cards")
        con.executemany("INSERT INTO cards VALUES(?,?,?,?)",
                        [(u, r.get("user", ""), r.get("name", r.get("user", "")),
                          r.get("token", "")) for u, r in users.items()])


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
# Monitoreo de paneles (heartbeat) — inventario en vivo, efimero en el contenedor
# ---------------------------------------------------------------------------

PING_OFF = 600   # seg cuando el monitoreo esta APAGADO (10 min)
PING_ON  = 60    # seg cuando esta ENCENDIDO (soporte, 1 min)
PANELS_MAX = 200  # tope de inventario (F5): se expulsa el mas viejo


def _load_panels():
    with closing(_db()) as con:
        rows = con.execute("SELECT id, apk, nfc, ip, seen, ram FROM panels").fetchall()
    return {r[0]: {"apk": r[1], "nfc": r[2], "ip": r[3], "seen": r[4],
                   "ram": r[5] or ""} for r in rows}


def _save_panel(pid, info):
    with closing(_db()) as con, con:
        con.execute("INSERT OR REPLACE INTO panels VALUES(?,?,?,?,?,?)",
                    (pid, info.get("apk"), info.get("nfc"), info.get("ip"),
                     info.get("seen"), info.get("ram", "")))
        con.execute("DELETE FROM panels WHERE id NOT IN "
                    "(SELECT id FROM panels ORDER BY seen DESC LIMIT ?)", (PANELS_MAX,))


def _monitor_on():
    with closing(_db()) as con:
        row = con.execute("SELECT v FROM config WHERE k='monitor'").fetchone()
    return bool(row and row[0] == "1")


def _set_monitor(on):
    with closing(_db()) as con, con:
        con.execute("INSERT OR REPLACE INTO config VALUES('monitor', ?)",
                    ("1" if on else "0",))


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
@limiter.limit("20 per minute", key_func=_auth_key,
               error_message="Demasiados intentos con esta tarjeta. Esperá un momento.")
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


@app.route("/panel-ping", methods=["POST"])
@limiter.limit("6 per minute", key_func=lambda: (request.form.get("id") or get_remote_address()))
def panel_ping():
    """Heartbeat del APK: registra version + estado NFC + ultima vez visto."""
    # F5: si hay secreto configurado, el ping debe traerlo (los ids son gratis de inventar)
    if PANEL_SECRET and (request.form.get("secret") or "") != PANEL_SECRET:
        return jsonify(ok=False), 403
    pid = (request.form.get("id") or "").strip()[:64]
    if not pid:
        return jsonify(ok=False), 400
    _save_panel(pid, {
        "apk":  (request.form.get("apk") or "?").strip()[:16],
        "nfc":  (request.form.get("nfc") or "?").strip()[:8],
        "ip":   get_remote_address(),
        "seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ram":  (request.form.get("ram") or "").strip()[:24],
    })
    # el panel se auto-ajusta a este intervalo: rapido si el monitoreo esta ON.
    return jsonify(ok=True, interval=PING_ON if _monitor_on() else PING_OFF)


@app.route("/admin/panels/monitor", methods=["POST"])
@require_admin
def admin_panels_monitor():
    _set_monitor(request.form.get("on") == "1")
    return redirect(url_for("admin_panels"))


def _pi_health():
    """Metricas del host para /admin/panels (F9). Docker no aisla /proc/loadavg
    ni /proc/meminfo, asi que reflejan la Pi real."""
    h = {}
    try:
        la = os.getloadavg()
        h["load"] = f"{la[0]:.2f} · {la[1]:.2f} · {la[2]:.2f}"
        h["load_hot"] = la[0] > 3.0   # Pi 5 = 4 nucleos
    except Exception:
        pass
    try:
        mem = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            mem[k] = int(v.strip().split()[0])
        tot, av = mem.get("MemTotal", 0) // 1024, mem.get("MemAvailable", 0) // 1024
        h["ram"] = f"{tot - av} / {tot} MB"
        h["ram_hot"] = tot > 0 and (tot - av) / tot > 0.85
    except Exception:
        pass
    try:
        du = shutil.disk_usage("/")
        h["disk"] = f"{du.used // 2**30} / {du.total // 2**30} GB"
        h["disk_hot"] = du.used / du.total > 0.85
    except Exception:
        pass
    try:
        t = int(open("/sys/class/thermal/thermal_zone0/temp").read().strip()) / 1000
        h["temp"] = f"{t:.0f} °C"
        h["temp_hot"] = t > 75
    except Exception:
        pass
    return h


@app.route("/admin/panels")
@require_admin
def admin_panels():
    """Tabla de estado de la flota (online/offline, version, NFC)."""
    panels = _load_panels()
    mon = _monitor_on()
    hp = _pi_health()
    def _tile(lbl, key):
        val = hp.get(key, "?")
        hot = hp.get(key + "_hot", False)
        col = "#f87171" if hot else "#3ddc97"
        return (f"<div style='background:#0f2442;border:1px solid #1e3a5f;border-radius:10px;"
                f"padding:.5rem .8rem;font-size:.78rem'><span style='color:#64748b'>{lbl}</span> "
                f"<b style='color:{col}'>{val}</b></div>")
    tiles = (_tile("Carga Pi", "load") + _tile("RAM Pi", "ram") +
             _tile("Disco", "disk") + _tile("Temp", "temp"))
    now = datetime.now(timezone.utc)
    rows = ""
    online = 0
    for pid, p in sorted(panels.items(), key=lambda kv: kv[0]):
        try:
            mins = (now - datetime.fromisoformat(p.get("seen", ""))).total_seconds() / 60
        except Exception:
            mins = 1e9
        is_on = mins < 10
        online += 1 if is_on else 0
        dot = "#3ddc97" if is_on else "#f87171"
        estado = "online" if is_on else f"hace {int(mins)} min" if mins < 1e8 else "?"
        nfc = p.get("nfc", "?")
        nfc_col = "#86efac" if nfc == "ok" else "#fca5a5" if nfc == "fail" else "#94a3b8"
        rows += (f"<tr><td><span style='color:{dot}'>&#9679;</span> {pid[:17]}</td>"
                 f"<td>v{p.get('apk','?')}</td>"
                 f"<td style='color:{nfc_col}'>{nfc}</td>"
                 f"<td>{p.get('ram') or '—'}</td>"
                 f"<td>{p.get('ip','?')}</td>"
                 f"<td>{estado}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='6' style='color:#64748b'>Sin paneles todavía (esperá el primer heartbeat).</td></tr>"
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Paneles - La Nube</title><style>
 body{{font-family:"Segoe UI",system-ui,sans-serif;background:#0a1628;color:#e2e8f0;padding:1.2rem}}
 h1{{font-size:1.15rem;color:#38bdf8;margin-bottom:.3rem}}
 .sub{{color:#64748b;font-size:.85rem;margin-bottom:1rem}}
 table{{width:100%;border-collapse:collapse;font-size:.88rem}}
 th,td{{text-align:left;padding:.5rem .6rem;border-bottom:1px solid #1e3a5f}}
 th{{color:#94a3b8;text-transform:uppercase;font-size:.7rem;letter-spacing:.04em}}
 a{{color:#38bdf8}}
</style></head><body>
 <h1>Paneles de la flota</h1>
 <div class="sub">{online} online / {len(panels)} totales &middot; server v{VERSION}</div>
 <div style="display:flex;gap:.6rem;flex-wrap:wrap;margin:0 0 1rem">{tiles}</div>
 <form method="POST" action="/admin/panels/monitor" style="margin:.2rem 0 1rem">
   <span style="font-size:.85rem">Monitoreo intensivo (soporte):
     <b style="color:{'#3ddc97' if mon else '#94a3b8'}">{'ON — paneles cada 1 min' if mon else 'OFF — paneles cada 10 min'}</b>
   </span>
   <input type="hidden" name="on" value="{'0' if mon else '1'}">
   <button style="margin-left:.6rem;padding:.35rem .9rem;border:none;border-radius:8px;
     background:{'#7c2d12' if mon else '#0369a1'};color:#fff;font-weight:600;cursor:pointer">
     {'Apagar' if mon else 'Encender'}</button>
 </form>
 <table><tr><th>Panel</th><th>APK</th><th>NFC</th><th>RAM panel</th><th>IP</th><th>Estado</th></tr>{rows}</table>
 <p style="margin-top:1rem"><a href="/admin">&larr; admin</a></p>
 <script>setTimeout(function(){{location.reload()}},30000)</script>
</body></html>"""
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store"
    return resp


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


@app.route("/test")
def test_page():
    """Página de diagnóstico para el panel (sin DevTools): muestra el UID leído,
    su forma canónica, si está registrada, y prueba el auto-logout del APK."""
    html = """<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Test NFC - La Nube</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0;font-family:"Segoe UI",system-ui,sans-serif}
  body{background:#0a1628;color:#e2e8f0;min-height:100vh;padding:1.1rem}
  h1{font-size:1.05rem;margin-bottom:.7rem;color:#38bdf8}
  .box{background:#0f2442;border:1px solid #1e3a5f;border-radius:12px;padding:1rem;margin-bottom:.7rem}
  .lbl{font-size:.68rem;color:#64748b;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.2rem}
  .big{font-family:monospace;font-size:1.5rem;color:#3ddc97;word-break:break-all}
  .row{display:flex;justify-content:space-between;font-size:.85rem;padding:.22rem 0}
  .ok{color:#86efac}.err{color:#fca5a5}.mut{color:#94a3b8}
  button{width:100%;padding:.8rem;margin-top:.5rem;border:none;border-radius:10px;
    background:#0369a1;color:#fff;font-size:.95rem;font-weight:600}
  button.warn{background:#7c2d12}
  #log{font-family:monospace;font-size:.72rem;color:#94a3b8;max-height:28vh;overflow:auto;white-space:pre-wrap}
  a{color:#38bdf8}
</style></head>
<body>
  <h1>Test NFC + Sesion &middot; v__VER__</h1>

  <div class="box">
    <div class="lbl">Ultimo UID leido (crudo)</div>
    <div class="big" id="raw">-</div>
    <div class="lbl" style="margin-top:.55rem">Canonico (hex)</div>
    <div class="big" id="canon" style="font-size:1.15rem;color:#7dd3fc">-</div>
    <div class="row"><span class="mut">Lecturas</span><span id="count">0</span></div>
    <div class="row"><span class="mut">Registrada?</span><span id="reg" class="mut">-</span></div>
  </div>

  <div class="box">
    <div class="row"><span class="mut">Puente APK (AndroidKiosk)</span><span id="bridge" class="err">NO</span></div>
    <div class="row"><span class="mut">Reloj</span><span id="clock">-</span></div>
    <button id="t1">Probar auto-logout en 1 min</button>
    <button id="t0" class="warn">Cancelar timer</button>
    <button id="clr" style="background:#7f1d1d">Borrar cookies / forzar logout</button>
    <div class="row" style="margin-top:.4rem"><span class="mut">Estado sesion</span><span id="sess" class="mut">sin iniciar</span></div>
  </div>

  <div class="box"><div class="lbl">Log</div><div id="log"></div></div>
  <p style="text-align:center"><a href="/">volver al kiosko</a></p>

<script>
  var raw=document.getElementById('raw'),canonEl=document.getElementById('canon'),
      countEl=document.getElementById('count'),regEl=document.getElementById('reg'),
      bridgeEl=document.getElementById('bridge'),clockEl=document.getElementById('clock'),
      sessEl=document.getElementById('sess'),logEl=document.getElementById('log');
  var n=0, logout_at=0;
  function log(m){ logEl.textContent=new Date().toLocaleTimeString()+"  "+m+"\\n"+logEl.textContent; }
  function canonUid(x){
    var s=String(x||'').replace(/[^0-9A-Fa-f]/g,'').toUpperCase();
    if(!s) return '';
    if(/^[0-9]+$/.test(s)){ try{ s=BigInt(s).toString(16).toUpperCase(); }catch(e){} }
    if(s.length%2) s='0'+s;
    while(s.length<8) s='0'+s;
    return s;
  }
  // El panel llama authenticate(uid); aca lo MOSTRAMOS en vez de loguear.
  window.authenticate=function(uid){
    n++; raw.textContent=uid; canonEl.textContent=canonUid(uid); countEl.textContent=n;
    log("authenticate('"+uid+"') -> canon "+canonUid(uid));
    regEl.textContent="consultando..."; regEl.className="mut";
    fetch('/uid-lookup?uid='+encodeURIComponent(uid)).then(function(r){return r.json();}).then(function(d){
      if(d.ok){ regEl.textContent="SI - "+(d.name||d.user); regEl.className="ok"; }
      else { regEl.textContent="NO registrada"; regEl.className="err"; }
    }).catch(function(){ regEl.textContent="error red"; regEl.className="err"; });
  };
  if(window.AndroidKiosk && typeof AndroidKiosk.startSession==='function'){ bridgeEl.textContent="SI"; bridgeEl.className="ok"; }
  document.getElementById('t1').onclick=function(){
    if(!(window.AndroidKiosk && AndroidKiosk.startSession)){ log("SIN puente APK (navegador, no kiosko)"); return; }
    AndroidKiosk.startSession(1); logout_at=Date.now()+60000;
    log("startSession(1) -> el APK carga /logout en 1 min");
  };
  document.getElementById('t0').onclick=function(){
    if(window.AndroidKiosk && AndroidKiosk.startSession){ AndroidKiosk.startSession(0); logout_at=0; log("timer cancelado"); }
  };
  document.getElementById('clr').onclick=function(){
    log("Borrando cookies/cache...");
    if(window.AndroidKiosk && AndroidKiosk.clearAll){ AndroidKiosk.clearAll(); }
    else { location.href='/reset'; }
  };
  setInterval(function(){
    clockEl.textContent=new Date().toLocaleTimeString();
    if(logout_at){ var s=Math.max(0,Math.round((logout_at-Date.now())/1000));
      sessEl.textContent="logout en "+s+"s"; sessEl.className=s<10?"err":"ok"; }
  },500);
  log("Test cargado. Acerca una tarjeta o pulsa el boton de sesion.");
</script>
</body></html>"""
    resp = make_response(html.replace("__VER__", VERSION))
    resp.headers["Cache-Control"] = "no-store, no-cache"
    return resp


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
