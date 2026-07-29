"""Resolve a merchant email to the subdomain of its real Frappe site."""
import json
import subprocess
from pathlib import Path


SITES_DIR = "sites"
CONTAINER = "dukkani-backend-1"
TENANTS_FILE = Path(__file__).resolve().parent / "tenants.json"
_QUERY = (
    "SELECT u.name FROM tabUser u "
    "JOIN `tabHas Role` r ON r.parent = u.name "
    "WHERE r.role IN ('Website Manager', 'Merchant Owner', 'Dukkani Store Owner', 'Dukkani Team Manager') "
    "AND r.parenttype = 'User' "
    "AND u.name NOT IN ('Administrator', 'Guest') "
    "AND u.enabled = 1 LIMIT 1;"
)


def _docker(args, timeout=20):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )


def _site_configs():
    """Return real tenant site names and database configurations."""
    result = _docker(["exec", CONTAINER, "python3", "-c", f"""
import json, os
out = []
for directory in os.listdir({SITES_DIR!r}):
    path = os.path.join({SITES_DIR!r}, directory, "site_config.json")
    if os.path.isfile(path) and "." in directory:
        try:
            out.append([directory, json.load(open(path))])
        except Exception:
            pass
print(json.dumps(out))
"""])
    try:
        return json.loads((result.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []


def build_index():
    """Read the enabled Website Manager directly from every tenant database."""
    index = {}
    for site_name, config in _site_configs():
        database = config.get("db_name")
        if not database:
            continue
        try:
            result = _docker([
                "exec", CONTAINER, "mysql", "-h", "db",
                "-u", config.get("db_user", database),
                f"-p{config.get('db_password', '')}", database,
                "-N", "-B", "-e", _QUERY,
            ])
        except subprocess.TimeoutExpired:
            continue
        email = (result.stdout or "").strip().split("\n")[0].strip()
        if email:
            index[email.lower()] = site_name
    return index


def _resolve_from_registry(email):
    """Resolve completed mobile signups from the provisioning registry."""
    try:
        tenants = json.loads(TENANTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    normalized = email.strip().lower()
    records = tenants.values() if isinstance(tenants, dict) else tenants
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("status") != "ready":
            continue
        if str(record.get("email", "")).strip().lower() != normalized:
            continue
        subdomain = str(record.get("subdomain", "")).strip().lower()
        if subdomain:
            return subdomain
    return None


def resolve(email):
    """Return only the merchant subdomain, or None when the email is unknown."""
    if not email:
        return None
    site_name = build_index().get(email.strip().lower())
    if site_name:
        return site_name.split(".")[0]
    return _resolve_from_registry(email)
