"""Social authentication bridge for the multi-tenant merchant app.

Google authentication is completed by the central Frappe site. Apple uses the
native identity token. Both paths resolve the verified email to a tenant and
create a normal Frappe session in that tenant.
"""

from __future__ import annotations

import hashlib
import base64
import json
import os
import subprocess
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import jwt
from jwt import PyJWKClient

import resolver


CONTAINER = "dukkani-backend-1"
BASE_DOMAIN = os.environ.get("DUKKANI_BASE_DOMAIN", "localhost").strip().lower()
CENTRAL_SITE = os.environ.get(
    "DUKKANI_SOCIAL_SITE", "https://www.dukani.ai"
).rstrip("/")
GOOGLE_CLIENT_ID = os.environ.get(
    "DUKKANI_GOOGLE_CLIENT_ID",
    "753450745142-mttrfe4u3bs1cg6ng0cph3obiimf4bdl.apps.googleusercontent.com",
).strip()
GOOGLE_REDIRECT_URI = (
    CENTRAL_SITE
    + "/api/method/frappe.integrations.oauth2_logins.login_via_google"
)
APPLE_AUDIENCE = os.environ.get(
    "DUKKANI_APPLE_AUDIENCE", "ai.dukkani.merchant"
).strip()
IDENTITIES_FILE = Path(__file__).resolve().parent / "social_identities.json"

_RUN_LOCK = threading.Lock()
_IDENTITY_LOCK = threading.Lock()
_APPLE_KEYS = PyJWKClient("https://appleid.apple.com/auth/keys", cache_keys=True)


class SocialAuthError(RuntimeError):
    pass


def google_authorize_url() -> str:
    state = base64.b64encode(
        json.dumps(
            {
                "site": CENTRAL_SITE,
                "token": os.urandom(24).hex(),
                "redirect_to": "/api/method/dukkani_mobile_social_ticket",
            }
        ).encode("utf-8")
    ).decode("ascii")
    return "https://accounts.google.com/o/oauth2/auth?" + urlencode(
        {
            "response_type": "code",
            "client_id": GOOGLE_CLIENT_ID,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "scope": "openid email profile",
            "prompt": "select_account",
            "state": state,
        }
    )


def exchange_google_ticket(ticket: str) -> dict:
    if len((ticket or "").strip()) != 64:
        raise SocialAuthError("رمز تسجيل Google غير صالح.")
    data = _get_json(
        CENTRAL_SITE
        + "/api/method/dukkani_social_ticket_exchange?"
        + urlencode({"ticket": ticket.strip()})
    )
    identity = data.get("message") if isinstance(data, dict) else None
    if not isinstance(identity, dict):
        raise SocialAuthError("انتهت صلاحية تسجيل Google، حاول مرة أخرى.")
    return _complete_identity(
        provider="google",
        subject="",
        email=str(identity.get("email") or ""),
        full_name=str(identity.get("full_name") or ""),
    )


def exchange_apple_token(
    identity_token: str,
    *,
    raw_nonce: str = "",
    full_name: str = "",
) -> dict:
    if not identity_token:
        raise SocialAuthError("لم تُرجع Apple بيانات تسجيل الدخول.")
    try:
        signing_key = _APPLE_KEYS.get_signing_key_from_jwt(identity_token)
        claims = jwt.decode(
            identity_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=APPLE_AUDIENCE,
            issuer="https://appleid.apple.com",
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except Exception as exc:
        raise SocialAuthError("تعذّر التحقق من تسجيل Apple.") from exc

    if raw_nonce:
        expected_nonce = hashlib.sha256(raw_nonce.encode("utf-8")).hexdigest()
        if claims.get("nonce") != expected_nonce:
            raise SocialAuthError("تعذّر التحقق من أمان تسجيل Apple.")

    subject = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().lower()
    saved = _identity_for("apple", subject)
    if not email and saved:
        email = str(saved.get("email") or "").strip().lower()
    if not full_name and saved:
        full_name = str(saved.get("full_name") or "").strip()
    if not email:
        raise SocialAuthError(
            "Apple لم تُرجع البريد الإلكتروني. احذف ربط دكاني من إعدادات "
            "Apple ID ثم حاول مرة أخرى."
        )

    _remember_identity("apple", subject, email, full_name)
    return _complete_identity(
        provider="apple",
        subject=subject,
        email=email,
        full_name=full_name,
    )


def _complete_identity(
    *,
    provider: str,
    subject: str,
    email: str,
    full_name: str,
) -> dict:
    email = email.strip().lower()
    if "@" not in email:
        raise SocialAuthError("مزود تسجيل الدخول لم يُرجع بريدًا صالحًا.")

    subdomain = resolver.resolve(email)
    if not subdomain:
        return {
            "status": "needs_signup",
            "provider": provider,
            "email": email,
            "full_name": full_name or email.split("@", 1)[0],
        }

    session = _create_tenant_session(subdomain, email)
    return {
        "status": "authenticated",
        "provider": provider,
        "email": email,
        "full_name": session.get("full_name") or full_name or email,
        "subdomain": subdomain,
        "base_url": f"https://{subdomain}.{BASE_DOMAIN}",
        "sid": session["sid"],
    }


_SESSION_CODE = r'''
import frappe, json
from frappe.sessions import Session

d = json.load(open("/tmp/dukkani_social_session_in.json", encoding="utf-8"))
email = (d.get("email") or "").strip().lower()
result = {"ok": False, "detail": "User is not allowed."}

if email and frappe.db.exists("User", email):
    user = frappe.get_doc("User", email)
    roles = set(frappe.get_roles(email))
    merchant_roles = {
        "Website Manager", "Merchant Owner", "System Manager",
        "Dukkani Store Owner",
    }
    if user.enabled and roles.intersection(merchant_roles):
        frappe.local.request = frappe._dict(cookies={}, headers={})
        frappe.local.form_dict = frappe._dict()
        frappe.local.request_ip = "127.0.0.1"
        full_name = user.full_name or user.first_name or email
        session = Session(
            user=email,
            full_name=full_name,
            user_type=user.user_type,
        )
        result = {"ok": True, "sid": session.sid, "full_name": full_name}

print("DUKKANI_SOCIAL_SESSION:" + json.dumps(result, ensure_ascii=False))
'''


def _create_tenant_session(subdomain: str, email: str) -> dict:
    site = f"{subdomain}.{BASE_DOMAIN}"
    with _RUN_LOCK:
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                CONTAINER,
                "bash",
                "-c",
                "cat > /tmp/dukkani_social_session.py",
            ],
            input=_SESSION_CODE.encode("utf-8"),
            check=True,
            timeout=30,
        )
        subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                CONTAINER,
                "bash",
                "-c",
                "cat > /tmp/dukkani_social_session_in.json",
            ],
            input=json.dumps({"email": email}).encode("utf-8"),
            check=True,
            timeout=30,
        )
        result = subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "bench", "--site", site, "console"],
            input=(
                "g={}; exec(open('/tmp/dukkani_social_session.py').read(), g)\n"
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    if result.returncode:
        raise SocialAuthError("تعذّر إنشاء جلسة المتجر.")
    marker = "DUKKANI_SOCIAL_SESSION:"
    for line in (result.stdout or "").splitlines():
        if marker in line:
            payload = json.loads(line.split(marker, 1)[1])
            if payload.get("ok") and payload.get("sid"):
                return payload
            break
    raise SocialAuthError("الحساب موثّق لكنه لا يملك صلاحية إدارة المتجر.")


def _get_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise SocialAuthError("تعذّر الاتصال بخدمة تسجيل الدخول.") from exc


def _identity_for(provider: str, subject: str) -> dict | None:
    if not subject:
        return None
    with _IDENTITY_LOCK:
        data = _load_identities()
        value = data.get(provider + ":" + subject)
        return value if isinstance(value, dict) else None


def _remember_identity(
    provider: str, subject: str, email: str, full_name: str
) -> None:
    if not subject:
        return
    with _IDENTITY_LOCK:
        data = _load_identities()
        data[provider + ":" + subject] = {
            "email": email,
            "full_name": full_name,
        }
        temp = IDENTITIES_FILE.with_suffix(".tmp")
        temp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(IDENTITIES_FILE)


def _load_identities() -> dict:
    try:
        data = json.loads(IDENTITIES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}
