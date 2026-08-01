# ============================================================
#  Dukkani — منطق التجهيز (Provisioner) — نسخة Windows/Docker
#  ينفّذ التجهيز مباشرةً عبر `docker exec` على حاوية الـ backend
#  (بدون bash script) — يشتغل على Windows وLinux بلا مشاكل مسارات.
#  يدير حالة كل تاجر في tenants.json.
# ============================================================
import json
import os
import re
import secrets
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # erpnext-provisioning/
TEMPLATE = BASE_DIR / "tenant_template.py"
STOREFRONT_STARTER = BASE_DIR / "storefront_starter.py"
STOREFRONT_CART = BASE_DIR / "storefront_cart.js"
TENANT_FINALIZER = BASE_DIR / "tenant_finalize.py"
STATE_FILE = Path(__file__).resolve().parent / "tenants.json"
JOBS_DIR = Path(__file__).resolve().parent / ".provisioning-jobs"
TRAEFIK_ROUTES_DIR = Path(os.environ.get("DUKKANI_TRAEFIK_ROUTES_DIR", "/docker/traefik/dynamic"))
FAST_TEMPLATE_DIR = os.environ.get(
    "DUKKANI_FAST_TEMPLATE_DIR",
    "/home/frappe/frappe-bench/sites/.dukkani-templates",
).rstrip("/")
EMAIL_SOURCE_SITE = os.environ.get("DUKKANI_EMAIL_SOURCE_SITE", "kareem.dukani.ai").strip()
EMAIL_ACCOUNT_NAME = os.environ.get("DUKKANI_EMAIL_ACCOUNT_NAME", "Dukkani Gmail").strip()

# إعدادات ستاك Dukkani على Docker
CONTAINER = os.environ.get(
    "DUKKANI_BENCH_CONTAINER",
    "bench-0001-000007-dukkanip",
).strip()
PRESS_CONTAINER = "press-backend-1"
PRESS_SITE = "press.dukani.ai"
PRESS_BENCH = os.environ.get(
    "DUKKANI_PRESS_BENCH",
    "bench-0001-000007-dukkanip",
).strip()
PRESS_PLAN = "Dukkani Internal Site"
PORT = 8090                         # المنفذ اللي عليه الـ frontend
BASE_DOMAIN = os.environ.get("DUKKANI_BASE_DOMAIN", "localhost").strip().lower()
PUBLIC_SCHEME = os.environ.get(
    "DUKKANI_PUBLIC_SCHEME", "https" if BASE_DOMAIN != "localhost" else "http"
)

# القيم المسموحة والمحجوزة
SUBDOMAIN_RE = r"^[a-z0-9](?:[a-z0-9-]{1,30}[a-z0-9])$"
RESERVED = {"www", "api", "app", "mail", "ftp", "root", "assets", "frontend"}

_lock = threading.Lock()
_active_jobs = set()

COUNTRY_TEMPLATE = {
    "Egypt": "egypt.sql.gz",
    "Saudi Arabia": "saudi-arabia.sql.gz",
    "Sudan": "sudan.sql.gz",
}


def site_admin_password():
    configured = os.environ.get("DUKKANI_SITE_ADMIN_PASSWORD", "").strip()
    return configured or secrets.token_urlsafe(32)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def set_status(subdomain: str, **fields) -> dict:
    """تحديث حالة تاجر بشكل آمن (thread-safe)."""
    with _lock:
        state = _read_state()
        record = state.get(subdomain, {"subdomain": subdomain})
        record.setdefault("created_at", _now())
        record.update(fields)
        record["updated_at"] = _now()
        state[subdomain] = record
        _write_state(state)
        return record


def get_status(subdomain: str):
    return _read_state().get(subdomain)


def list_tenants() -> list:
    return list(_read_state().values())


def _job_path(subdomain: str) -> Path:
    return JOBS_DIR / f"{subdomain}.json"


def _save_job(subdomain: str, merchant_name: str, email: str,
              password: str, country: str) -> None:
    JOBS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = _job_path(subdomain)
    path.write_text(json.dumps({
        "subdomain": subdomain,
        "merchant_name": merchant_name,
        "email": email,
        "password": password,
        "country": country,
    }, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)


def _delete_job(subdomain: str) -> None:
    try:
        _job_path(subdomain).unlink()
    except FileNotFoundError:
        pass


def _run_saved_job(payload: dict) -> None:
    subdomain = payload["subdomain"]
    try:
        provision(
            subdomain,
            payload["merchant_name"],
            payload.get("email", ""),
            payload.get("password", ""),
            payload.get("country", "Saudi Arabia"),
        )
    finally:
        record = get_status(subdomain) or {}
        if record.get("status") == "failed":
            _delete_job(subdomain)
        with _lock:
            _active_jobs.discard(subdomain)


def start_provision(subdomain: str, merchant_name: str, email: str = "",
                    password: str = "", country: str = "Saudi Arabia") -> bool:
    """Persist and start a provisioning job, once per tenant.

    Persisting the short-lived payload lets the service resume safely after a
    deploy/restart. The file is mode 0600 and is removed as soon as the core
    store is ready.
    """
    payload = {
        "subdomain": subdomain,
        "merchant_name": merchant_name,
        "email": email,
        "password": password,
        "country": country,
    }
    _save_job(**payload)
    with _lock:
        if subdomain in _active_jobs:
            return False
        _active_jobs.add(subdomain)
    threading.Thread(target=_run_saved_job, args=(payload,), daemon=True).start()
    return True


def resume_pending_jobs() -> int:
    """Resume durable jobs after the API service restarts."""
    if not JOBS_DIR.exists():
        return 0
    resumed = 0
    for path in JOBS_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            status = (get_status(payload["subdomain"]) or {}).get("status")
            if status in {"pending", "provisioning"}:
                if start_provision(**payload):
                    resumed += 1
            else:
                path.unlink(missing_ok=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            path.unlink(missing_ok=True)
    return resumed


def _abbr(name: str) -> str:
    a = "".join(w[0] for w in name.split()[:3] if w).upper()
    return a or "DKN"


def _docker(args, timeout=900, text_input=None, binary_input=None):
    """يشغّل `docker <args>` ويرجّع CompletedProcess."""
    kwargs = {"capture_output": True, "timeout": timeout}
    if binary_input is not None:
        kwargs["input"] = binary_input
    else:
        kwargs["text"] = True
        if text_input is not None:
            kwargs["input"] = text_input
    return subprocess.run(["docker", *args], **kwargs)


def _site_exists(site: str) -> bool:
    r = _docker(["exec", CONTAINER, "test", "-f", f"sites/{site}/site_config.json"], timeout=30)
    return r.returncode == 0


def _press_console(code: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run trusted bridge code inside Press without exposing an HTTP API key."""
    return _docker(
        [
            "exec", "-i", PRESS_CONTAINER, "bash", "-lc",
            f"cd /home/frappe/frappe-bench && bench --site {PRESS_SITE} console",
        ],
        timeout=timeout,
        text_input=f"exec({code!r})\n",
    )


def _ensure_press_site(subdomain: str, site: str, admin_password: str) -> None:
    """Create the tenant through Press and wait for Agent to install all apps."""
    code = f"""
import frappe
site_name = {site!r}
if not frappe.db.exists("Site", site_name):
    bench = frappe.get_doc("Bench", {PRESS_BENCH!r})
    doc = frappe.get_doc({{
        "doctype": "Site",
        "subdomain": {subdomain!r},
        "domain": {BASE_DOMAIN!r},
        "status": "Pending",
        "server": bench.server,
        "bench": bench.name,
        "group": bench.group,
        "cluster": bench.cluster,
        "team": bench.team,
        "plan": {PRESS_PLAN!r},
        "free": 1,
        "admin_password": {admin_password!r},
        "apps": [{{"app": "frappe"}}, {{"app": "erpnext"}}, {{"app": "builder"}}],
    }})
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    print("DUKKANI_PRESS_CREATED", doc.name, doc.flags.get("new_site_agent_job_name"))
else:
    doc = frappe.get_doc("Site", site_name)
    print("DUKKANI_PRESS_EXISTS", doc.name, doc.status)
"""
    result = _press_console(code, timeout=180)
    output = (result.stdout or "") + (result.stderr or "")
    site_marker = re.compile(
        rf"DUKKANI_PRESS_(?:CREATED|EXISTS)\s+{re.escape(site)}(?:\s|$)"
    )
    if result.returncode != 0 or not site_marker.search(output):
        raise RuntimeError("Press registration failed: " + _tail(output, lines=40))

    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        if _site_exists(site):
            apps = _docker(
                ["exec", CONTAINER, "bench", "--site", site, "list-apps"],
                timeout=60,
            )
            installed = set((apps.stdout or "").lower().split())
            if {"frappe", "erpnext", "builder"}.issubset(installed):
                break
        time.sleep(5)
    else:
        raise TimeoutError("Press Site creation did not complete within 20 minutes")

    sync_code = f"""
import frappe
site_name = {site!r}
jobs = frappe.get_all(
    "Agent Job",
    filters={{"site": site_name, "job_type": "New Site"}},
    pluck="name",
    order_by="creation desc",
    limit=1,
)
if jobs:
    job = frappe.get_doc("Agent Job", jobs[0])
    if job.status != "Success":
        job.succeed_and_process_job_updates()
frappe.db.set_value("Site", site_name, "status", "Active", update_modified=False)
frappe.db.commit()
print("DUKKANI_PRESS_ACTIVE", site_name)
"""
    synced = _press_console(sync_code, timeout=180)
    sync_output = (synced.stdout or "") + (synced.stderr or "")
    active_marker = re.compile(
        rf"DUKKANI_PRESS_ACTIVE\s+{re.escape(site)}(?:\s|$)"
    )
    if synced.returncode != 0 or not active_marker.search(sync_output):
        raise RuntimeError("Press status sync failed: " + _tail(sync_output, lines=40))


def _register_existing_press_site(
    subdomain: str,
    site: str,
    admin_password: str,
) -> None:
    """Register an existing Frappe site in Press without recreating it.

    A previous or resumed provisioning attempt can leave the physical site in
    place before Press receives its Site document.  Inserting a normal Press
    Site would enqueue a destructive duplicate ``new_site`` Agent job.  This
    bridge skips only Press's ``after_insert`` provisioning hook, while still
    running validation and inserting the app child records.
    """
    code = f"""
import frappe
from press.press.doctype.site.site import Site

site_name = {site!r}
if frappe.db.exists("Site", site_name):
    doc = frappe.get_doc("Site", site_name)
    print("DUKKANI_PRESS_EXISTS", doc.name, doc.status)
else:
    bench = frappe.get_doc("Bench", {PRESS_BENCH!r})
    doc = frappe.get_doc({{
        "doctype": "Site",
        "subdomain": {subdomain!r},
        "domain": {BASE_DOMAIN!r},
        "status": "Active",
        "server": bench.server,
        "bench": bench.name,
        "group": bench.group,
        "cluster": bench.cluster,
        "team": bench.team,
        "plan": {PRESS_PLAN!r},
        "free": 1,
        "admin_password": {admin_password!r},
        "apps": [
            {{"app": "frappe"}},
            {{"app": "erpnext"}},
            {{"app": "builder"}},
        ],
    }})
    original_after_insert = Site.after_insert
    original_on_update = Site.on_update
    Site.after_insert = lambda self: None
    Site.on_update = lambda self: None
    try:
        doc.insert(ignore_permissions=True)
    finally:
        Site.after_insert = original_after_insert
        Site.on_update = original_on_update
    doc._create_default_site_domain()
    frappe.db.commit()
    print("DUKKANI_PRESS_REGISTERED", doc.name, doc.status)
"""
    result = _press_console(code, timeout=180)
    output = (result.stdout or "") + (result.stderr or "")
    site_marker = re.compile(
        rf"DUKKANI_PRESS_(?:REGISTERED|EXISTS)\s+{re.escape(site)}(?:\s|$)"
    )
    if result.returncode != 0 or not site_marker.search(output):
        raise RuntimeError(
            "Existing Press Site registration failed: "
            + _tail(output, lines=40)
        )


def _fast_template(country: str) -> str | None:
    filename = COUNTRY_TEMPLATE.get(country)
    if not filename:
        return None
    path = f"{FAST_TEMPLATE_DIR}/{filename}"
    exists = _docker(["exec", CONTAINER, "test", "-f", path], timeout=30)
    return path if exists.returncode == 0 else None


def _record_step(subdomain: str, step: str, started: float, **fields) -> None:
    set_status(
        subdomain,
        provisioning_step=step,
        elapsed_seconds=round(time.monotonic() - started, 1),
        **fields,
    )


def _copy_into_container(source: Path, target: str) -> None:
    result = _docker(
        [
            "exec", "-i", "-u", "root", CONTAINER,
            "bash", "-c", f"rm -f {target} && cat > {target} && chmod 644 {target}",
        ],
        timeout=60,
        binary_input=source.read_bytes(),
    )
    if result.returncode != 0:
        raise RuntimeError(_tail(result.stderr or result.stdout))


def _run_finalizer(site: str, merchant_name: str, owner_email: str,
                   password: str, country: str) -> subprocess.CompletedProcess:
    _copy_into_container(TENANT_FINALIZER, "/tmp/tenant_finalize.py")
    env_args = []
    for key, value in {
        "MERCHANT_NAME": merchant_name,
        "MERCHANT_EMAIL": owner_email,
        "MERCHANT_PASSWORD": password,
        "MERCHANT_COUNTRY": country,
    }.items():
        env_args += ["-e", f"{key}={value}"]
    return _docker(
        ["exec", "-i", *env_args, CONTAINER, "bench", "--site", site, "console"],
        timeout=180,
        text_input=(
            "g={'__name__':'__main__'}; "
            "exec(compile(open('/tmp/tenant_finalize.py').read(), "
            "'/tmp/tenant_finalize.py', 'exec'), g, g)\n"
        ),
    )


def ensure_public_route(subdomain: str) -> None:
    """Create an explicit Traefik router so Let's Encrypt can issue this store's certificate."""
    if BASE_DOMAIN == "localhost":
        return
    host = f"{subdomain}.{BASE_DOMAIN}"
    key = re.sub(r"[^a-z0-9-]", "-", subdomain.lower())
    canonical = f"store-{key}-canonical"
    builder_canonical = f"store-{key}-builder-canonical"
    home = f"store-{key}-home"
    config = {
        "http": {"middlewares": {
            canonical: {
                "redirectRegex": {
                    "regex": rf"^https?://{re.escape(host)}/shop/?$",
                    "replacement": f"https://{host}/",
                    "permanent": True,
                }
            },
            builder_canonical: {
                "redirectRegex": {
                    "regex": rf"^https?://{re.escape(host)}/builder/$",
                    "replacement": f"https://{host}/builder",
                    "permanent": True,
                }
            },
            home: {"replacePath": {"path": "/shop"}},
        }, "routers": {
            home: {
                "rule": f"Host(`{host}`) && Path(`/`)",
                "entryPoints": ["websecure"], "priority": 120,
                "middlewares": [home],
                "service": "dukkani-press-web@file",
                "tls": {"certResolver": "letsencrypt"},
            },
            canonical: {
                "rule": f"Host(`{host}`) && (Path(`/shop`) || Path(`/shop/`))",
                "entryPoints": ["websecure"], "priority": 110,
                "middlewares": [canonical],
                "service": "dukkani-press-web@file",
                "tls": {"certResolver": "letsencrypt"},
            },
            builder_canonical: {
                "rule": f"Host(`{host}`) && Path(`/builder/`)",
                "entryPoints": ["websecure"], "priority": 115,
                "middlewares": [builder_canonical],
                "service": "dukkani-press-web@file",
                "tls": {"certResolver": "letsencrypt"},
            },
            f"store-{key}-api": {
                "rule": f"Host(`{host}`) && (Path(`/merchant-access`) || Path(`/merchant-access.html`) || Path(`/merchant-login`) || Path(`/me`) || Path(`/customer-login`) || Path(`/customer-login.html`) || Path(`/customer-account`) || Path(`/customer-account.html`) || Path(`/customer-orders`) || Path(`/customer-orders.html`) || Path(`/signup`) || Path(`/signup.html`) || Path(`/customer-signup`) || Path(`/customer-signup.html`) || PathPrefix(`/shop/customer-register`) || PathPrefix(`/shop/customer-login`) || PathPrefix(`/shop/customer-orders`) || PathPrefix(`/shop/reverse-geocode`) || PathPrefix(`/shop/order`) || PathPrefix(`/shop/review`) || PathPrefix(`/shop/products`))",
                "entryPoints": ["websecure"], "priority": 100,
                "service": "dukkani-api@file", "tls": {"certResolver": "letsencrypt"},
            },
            f"store-{key}-web": {
                "rule": f"Host(`{host}`)", "entryPoints": ["websecure"],
                "service": "dukkani-press-web@file", "tls": {"certResolver": "letsencrypt"},
            },
        }}
    }
    TRAEFIK_ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    # Traefik's directory provider accepts .yml/.yaml/.toml. JSON is valid YAML,
    # so keep deterministic stdlib serialization while using a supported suffix.
    target = TRAEFIK_ROUTES_DIR / f"store-{key}.yml"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)


def clone_outgoing_email_account(site: str) -> bool:
    """Copy the shared outgoing Gmail account into a freshly created tenant.

    Passwords are decrypted and moved inside the backend container only; they
    are never written to this process logs or the tenant status file.
    """
    if not EMAIL_SOURCE_SITE or not EMAIL_ACCOUNT_NAME:
        return False

    writer = f"""
import frappe
from frappe.utils.password import get_decrypted_password
name = {EMAIL_ACCOUNT_NAME!r}
if not frappe.db.exists("Email Account", name):
    raise SystemExit(0)
doc = frappe.get_doc("Email Account", name)
password = get_decrypted_password("Email Account", name, "password", raise_exception=False) or ""
values = {{
    "email_account_name": doc.email_account_name,
    "email_id": doc.email_id,
    "service": doc.service,
    "enable_incoming": 0,
    "enable_outgoing": 1,
    "default_incoming": 0,
    "default_outgoing": 1,
    "smtp_server": doc.smtp_server,
    "smtp_port": doc.smtp_port,
    "use_tls": doc.use_tls,
    "use_ssl": doc.use_ssl,
    "always_use_account_email_id_as_sender": doc.always_use_account_email_id_as_sender,
    "append_emails_to_sent_folder": doc.append_emails_to_sent_folder,
}}
frappe.local.flags.dukkani_email_payload = values
open("/tmp/dukkani_email_payload.json", "w").write(frappe.as_json(values))
open("/tmp/dukkani_email_password.txt", "w").write(password)
"""
    source = _docker(
        ["exec", "-i", CONTAINER, "bench", "--site", EMAIL_SOURCE_SITE, "console"],
        timeout=120,
        text_input=writer + "\n",
    )
    if source.returncode != 0:
        return False

    installer = f"""
import json
import frappe
name = {EMAIL_ACCOUNT_NAME!r}
try:
    values = json.load(open("/tmp/dukkani_email_payload.json"))
    password = open("/tmp/dukkani_email_password.txt").read()
except FileNotFoundError:
    raise SystemExit(0)
values.update({{"doctype": "Email Account", "password": password}})
if frappe.db.exists("Email Account", name):
    doc = frappe.get_doc("Email Account", name)
    doc.update(values)
    doc.save(ignore_permissions=True)
else:
    doc = frappe.get_doc(values)
    doc.insert(ignore_permissions=True)
frappe.db.commit()
print("Dukkani outgoing email account ready")
"""
    dest = _docker(
        ["exec", "-i", CONTAINER, "bench", "--site", site, "console"],
        timeout=180,
        text_input=installer + "\n",
    )
    _docker(["exec", CONTAINER, "rm", "-f", "/tmp/dukkani_email_payload.json", "/tmp/dukkani_email_password.txt"], timeout=30)
    return dest.returncode == 0


def send_store_ready_email(site: str, email: str, merchant_name: str,
                           public_url: str) -> bool:
    """Send the merchant a welcome message after provisioning completes."""
    if not email or "@" not in email:
        return False
    login_url = public_url.rstrip("/") + "/login"
    subject = "متجرك على دكاني جاهز"
    message = f"""<div dir='rtl' style='font-family:Arial,sans-serif;line-height:1.9'>
<h2>أهلًا {merchant_name}</h2>
<p>تم إنشاء متجرك وتجهيزه بنجاح.</p>
<p><a href='{login_url}' style='display:inline-block;padding:11px 20px;background:#294B3B;color:#fff;text-decoration:none;border-radius:8px'>الدخول إلى متجرك</a></p>
<p>رابط المتجر: <a href='{public_url}'>{public_url}</a></p>
</div>"""
    code = f"""
import frappe
frappe.sendmail(
    recipients=[{email!r}],
    subject={subject!r},
    message={message!r},
    now=True,
)
frappe.db.commit()
print("DUKKANI_WELCOME_EMAIL_SENT")
"""
    result = _docker(
        ["exec", "-i", CONTAINER, "bench", "--site", site, "console"],
        timeout=180,
        text_input=code + "\n",
    )
    return (
        result.returncode == 0
        and "DUKKANI_WELCOME_EMAIL_SENT" in (result.stdout or "")
    )


def provision(subdomain: str, merchant_name: str,
              email: str = "", password: str = "",
              country: str = "Saudi Arabia") -> None:
    """ينشئ Site معزول + يطبّق قالب دكاني، ويحدّث الحالة."""
    site = f"{subdomain}.{BASE_DOMAIN}"
    public_url = f"{PUBLIC_SCHEME}://{site}" + (f":{PORT}" if BASE_DOMAIN == "localhost" else "")
    owner_email = email or f"owner@{subdomain}.dukkani.ai"
    abbr = _abbr(merchant_name)
    started = time.monotonic()
    set_status(subdomain, status="provisioning", merchant_name=merchant_name,
               email=owner_email, country=country,
               url=public_url, error=None, started_at=_now(),
               provisioning_step="starting", elapsed_seconds=0)
    try:
        ensure_public_route(subdomain)
        template = _fast_template(country)
        used_fast_template = False
        # (3) إنشاء الـ Site + قاعدة بيانات معزولة + ERPNext
        if not _site_exists(site):
            _record_step(
                subdomain,
                "creating_press_site",
                started,
                fast_path=False,
            )
            _ensure_press_site(subdomain, site, site_admin_password())
        else:
            _record_step(
                subdomain,
                "registering_existing_press_site",
                started,
                fast_path=False,
            )
            _register_existing_press_site(
                subdomain,
                site,
                site_admin_password(),
            )

        if used_fast_template:
            _record_step(subdomain, "personalizing_store", started, fast_path=True)
            finalize = _run_finalizer(
                site, merchant_name, owner_email, password, country
            )
            if (
                finalize.returncode != 0
                or "Dukkani tenant personalized successfully"
                not in (finalize.stdout or "")
            ):
                return set_status(
                    subdomain,
                    status="failed",
                    error=_tail(finalize.stderr or finalize.stdout, lines=40),
                )
            _docker(
                ["exec", CONTAINER, "bench", "--site", site, "clear-cache"],
                timeout=120,
            )
            _docker(
                [
                    "exec", CONTAINER, "bench", "--site", site,
                    "clear-website-cache",
                ],
                timeout=120,
            )
            total = round(time.monotonic() - started, 1)
            set_status(
                subdomain,
                status="ready",
                url=public_url,
                fast_path=True,
                provisioning_step="ready",
                elapsed_seconds=total,
                storefront_status="ready",
                log_tail=_tail(finalize.stdout or ""),
            )
            _delete_job(subdomain)
            # Email is not required for first login. Configure it after the
            # customer can already enter the store.
            email_ready = clone_outgoing_email_account(site)
            welcome_sent = send_store_ready_email(
                site, owner_email, merchant_name, public_url
            )
            set_status(
                subdomain,
                status="ready",
                email_status="ready" if email_ready else "missing",
                welcome_email_status="sent" if welcome_sent else "failed",
                elapsed_seconds=total,
            )
            return

        # Install ERPNext as a resumable step. A previous interrupted request
        # may have created the Frappe site but stopped during ERPNext sync.
        _record_step(subdomain, "installing_erpnext", started, fast_path=False)
        install_erpnext = _docker(
            ["exec", CONTAINER, "bench", "--site", site, "install-app", "erpnext"],
            timeout=1200,
        )
        erpnext_output = (install_erpnext.stdout or "") + (install_erpnext.stderr or "")
        if install_erpnext.returncode != 0 and "already installed" not in erpnext_output:
            return set_status(subdomain, status="failed", error=_tail(erpnext_output, lines=40))

        # (4) نسخ القالب داخل الحاوية عبر stdin ثم تطبيقه
        _record_step(subdomain, "applying_dukkani_template", started)
        _copy_into_container(TEMPLATE, "/tmp/tenant_template.py")

        env_args = []
        for k, v in {
            "MERCHANT_NAME": merchant_name, "MERCHANT_ABBR": abbr,
            "MERCHANT_EMAIL": owner_email, "MERCHANT_PASSWORD": password or "",
            "MERCHANT_COUNTRY": country,
        }.items():
            env_args += ["-e", f"{k}={v}"]

        run = _docker(["exec", "-i", *env_args, CONTAINER,
                       "bench", "--site", site, "console"],
                      timeout=600,
                      text_input="g={'__name__':'__main__'}; exec(compile(open('/tmp/tenant_template.py').read(), '/tmp/tenant_template.py', 'exec'), g, g)\n")

        if "اكتمل تطبيق القالب بنجاح" not in (run.stdout or "") and run.returncode != 0:
            return set_status(subdomain, status="failed",
                              error=_tail(run.stderr or run.stdout))
        email_ready = clone_outgoing_email_account(site)

        # At this point the merchant user, roles, mobile endpoints and core
        # ERPNext setup are ready. Do not block the mobile app while the
        # editable storefront/Builder assets are being prepared.
        _docker(["exec", CONTAINER, "bench", "--site", site, "clear-cache"], timeout=120)
        _docker(["exec", CONTAINER, "bench", "--site", site, "clear-website-cache"], timeout=120)
        set_status(subdomain, status="ready",
                   url=public_url,
                   email_status="ready" if email_ready else "missing",
                   storefront_status="provisioning",
                   provisioning_step="ready",
                   elapsed_seconds=round(time.monotonic() - started, 1),
                   log_tail=_tail(run.stdout or ""))
        _delete_job(subdomain)

        # Builder + editable starter storefronts. Each page reads products
        # from this tenant's own ERPNext database at render time.
        install_builder = _docker(
            ["exec", CONTAINER, "bench", "--site", site, "install-app", "builder"],
            timeout=600,
        )
        install_output = (install_builder.stdout or "") + (install_builder.stderr or "")
        if install_builder.returncode != 0 and "already installed" not in install_output:
            return set_status(subdomain, status="ready",
                              storefront_status="failed",
                              storefront_error=_tail(install_output),
                              error=None)

        migrate = _docker(
            ["exec", CONTAINER, "bench", "--site", site, "migrate"], timeout=900
        )
        if migrate.returncode != 0:
            return set_status(subdomain, status="ready",
                              storefront_status="failed",
                              storefront_error=_tail(migrate.stderr or migrate.stdout),
                              error=None)

        starter = STOREFRONT_STARTER.read_bytes()
        storefront_cart = STOREFRONT_CART.read_bytes()
        _docker(["exec", "-i", CONTAINER, "bash", "-c",
                 "cat > /tmp/storefront_starter.py"], timeout=60, binary_input=starter)
        _docker(["exec", "-i", CONTAINER, "bash", "-c",
                 "cat > /tmp/storefront_cart.js"], timeout=60, binary_input=storefront_cart)
        starter_run = _docker(
            ["exec", "-i", "-e", f"MERCHANT_EMAIL={owner_email}", CONTAINER,
             "bench", "--site", site, "console"],
            timeout=600,
            text_input="g={'__name__':'__main__'}; exec(compile(open('/tmp/storefront_starter.py').read(), '/tmp/storefront_starter.py', 'exec'), g, g)\n",
        )
        if starter_run.returncode != 0:
            return set_status(subdomain, status="ready",
                              storefront_status="failed",
                              storefront_error=_tail(starter_run.stderr or starter_run.stdout),
                              error=None)

        # Publish the default Boutique Builder page at /shop after the starter
        # pages exist, and finalize the merchant owner.
        finalize = _run_finalizer(
            site, merchant_name, owner_email, password, country
        )
        if (
            finalize.returncode != 0
            or "Dukkani tenant personalized successfully"
            not in (finalize.stdout or "")
        ):
            return set_status(
                subdomain,
                status="ready",
                storefront_status="failed",
                storefront_error=_tail(
                    finalize.stderr or finalize.stdout, lines=40
                ),
                error=None,
            )

        # مسح الكاش (تخطّي معالج الإعداد يأخذ مفعوله)
        _docker(["exec", CONTAINER, "bench", "--site", site, "clear-cache"], timeout=120)
        _docker(["exec", CONTAINER, "bench", "--site", site, "clear-website-cache"], timeout=120)

        set_status(subdomain, status="ready",
                   url=public_url,
                   storefront_status="ready",
                   log_tail=_tail((run.stdout or "") + "\n" + (starter_run.stdout or "")))
        welcome_sent = send_store_ready_email(
            site, owner_email, merchant_name, public_url
        )
        set_status(
            subdomain,
            welcome_email_status="sent" if welcome_sent else "failed",
        )
    except subprocess.TimeoutExpired:
        set_status(subdomain, status="failed", error="انتهت المهلة (900 ثانية)")
    except Exception as exc:                                   # noqa: BLE001
        set_status(subdomain, status="failed", error=str(exc))


def _tail(text: str, lines: int = 15) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])
