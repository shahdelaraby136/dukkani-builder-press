#!/usr/bin/env python3
# ============================================================
#  Dukkani — Provisioning API (مكتبة بايثون القياسية فقط)
#  بديل خفيف لـ FastAPI لا يحتاج أي تثبيت خارجي.
#  نفس نقاط النهاية، ويعيد استخدام provisioner.py.
#
#  التشغيل (بصلاحية Docker):
#     python3 server.py            # على http://0.0.0.0:9000
# ============================================================
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import provisioner as pv
import resolver
import shopapi
import social_auth
from api_security import allowed_origin, public_tenant, public_tenants

# مزامنة تلقائية للوحة الأدمن كل SYNC_EVERY ثانية
SYNC_EVERY = 90
SYNC_SCRIPT = Path(__file__).resolve().parent.parent / "sync_merchants_win.py"

PORT = 9000
API_DIR = Path(__file__).resolve().parent
REGISTER_HTML = API_DIR / "register.html"
ONBOARDING_HTML = API_DIR / "onboarding.html"
SIGNUP_HTML = API_DIR / "signup.html"
CUSTOMER_LOGIN_HTML = API_DIR / "customer-login.html"
CUSTOMER_SIGNUP_HTML = API_DIR / "customer-signup.html"
CUSTOMER_ACCOUNT_HTML = API_DIR / "customer-account.html"
CUSTOMER_ORDERS_HTML = API_DIR / "customer-orders.html"
WEB_LOGIN_HTML = API_DIR / "web-login.html"
LANDING_DIR = API_DIR / "landing"
LANDING_HTML = LANDING_DIR / "index.html"
LANDING_ASSETS = LANDING_DIR / "images"
ACCOUNTS_FILE = API_DIR / "accounts.json"

# الدول المدعومة (كود الدولة → الدولة/العملة) — أساس تحديد جنسية المسجِّل
COUNTRY_BY_CODE = {
    "966": {"country": "Saudi Arabia", "currency": "SAR"},
    "20":  {"country": "Egypt",        "currency": "EGP"},
    "249": {"country": "Sudan",        "currency": "SDG"},
}


def _valid_subdomain(v: str):
    v = (v or "").strip().lower()
    if not re.match(pv.SUBDOMAIN_RE, v):
        return None, "النطاق الفرعي يجب أن يكون حروفاً/أرقاماً إنجليزية صغيرة و '-' (3–32 حرفاً)."
    if v in pv.RESERVED:
        return None, f"النطاق '{v}' محجوز، اختر اسماً آخر."
    return v, None


class Handler(BaseHTTPRequestHandler):
    def _host(self) -> str:
        return (self.headers.get("Host") or "").split(":", 1)[0].lower()

    def _is_tenant_host(self) -> bool:
        host = self._host()
        central_hosts = {
            pv.BASE_DOMAIN,
            f"www.{pv.BASE_DOMAIN}",
            f"admin.{pv.BASE_DOMAIN}",
        }
        return bool(
            host
            and host not in central_hosts
            and host.endswith("." + pv.BASE_DOMAIN)
        )

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        origin = allowed_origin(self.headers.get("Origin"), pv.BASE_DOMAIN)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, {})

    def _send_html(self, path: Path):
        html = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _redirect(self, url):
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_unified_merchant_login(self):
        """Serve Dukkani's branded login UI with tenant-aware authentication."""
        query = parse_qs(urlparse(self.path).query)
        email = (query.get("email") or [""])[0].strip()
        error = (query.get("error") or [""])[0].strip()
        try:
            html = WEB_LOGIN_HTML.read_text(encoding="utf-8")
        except OSError:
            return self._send(500, {"detail": "تعذر تحميل صفحة الدخول"})
        html = html.replace("__PRESET_EMAIL_JSON__", json.dumps(email))
        html = html.replace("__INITIAL_ERROR_JSON__", json.dumps(error))
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return

        try:
            request = Request(
                "http://127.0.0.1:8090/login?redirect-to=%2Fdesk",
                headers={"Host": pv.BASE_DOMAIN, "X-Forwarded-Proto": "https"},
            )
            with urlopen(request, timeout=20) as response:
                html = response.read().decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError):
            return self._send(502, {"detail": "تعذّر تحميل صفحة الدخول"})

        bridge = f"""
<script id="dukkani-unified-merchant-login">
(() => {{
  const presetEmail = {json.dumps(email)};
  const initialError = {json.dumps(error)};
  const showError = (message) => {{
    let box = document.getElementById("dukkani-login-error");
    if (!box) {{
      box = document.createElement("div");
      box.id = "dukkani-login-error";
      box.className = "alert alert-danger";
      box.style.marginBottom = "16px";
      const body = document.querySelector(".for-login .page-card-body");
      if (body) body.prepend(box);
    }}
    if (box) box.textContent = message;
  }};
  document.addEventListener("DOMContentLoaded", () => {{
    const email = document.getElementById("login_email");
    if (email && presetEmail) email.value = presetEmail;
    if (initialError) showError("البريد الإلكتروني أو كلمة المرور غير صحيحة.");
  }});
  document.addEventListener("click", async (event) => {{
    const signup = event.target.closest && event.target.closest(".sign-up-message a");
    if (signup && document.querySelector("section.for-login")) {{
      event.preventDefault();
      event.stopImmediatePropagation();
      location.assign("/signup");
      return;
    }}
    const emailLink = event.target.closest && event.target.closest(".btn-login-with-email-link");
    if (emailLink) {{
      event.preventDefault();
      event.stopImmediatePropagation();
      const value = (document.getElementById("login_email")?.value || "").trim().toLowerCase();
      if (!value) return showError("اكتب البريد الإلكتروني أولاً.");
      try {{
        const response = await fetch("/resolve?email=" + encodeURIComponent(value), {{cache: "no-store"}});
        const data = await response.json();
        if (!response.ok || !data.subdomain) throw new Error();
        location.assign("https://" + data.subdomain + ".dukani.ai/login#login-with-email-link");
      }} catch (_) {{
        showError("لا يوجد متجر مرتبط بهذا البريد الإلكتروني.");
      }}
    }}
  }}, true);
  document.addEventListener("submit", async (event) => {{
    if (!event.target.matches(".form-login")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const email = (document.getElementById("login_email")?.value || "").trim().toLowerCase();
    const password = document.getElementById("login_password")?.value || "";
    if (!email || !password) return showError("اكتب البريد الإلكتروني وكلمة المرور.");
    try {{
      const response = await fetch("/resolve?email=" + encodeURIComponent(email), {{cache: "no-store"}});
      const data = await response.json();
      if (!response.ok || !data.subdomain) throw new Error();
      const form = document.createElement("form");
      form.method = "POST";
      form.action = "https://" + data.subdomain + ".dukani.ai/merchant-login";
      for (const [name, value] of Object.entries({{usr: email, pwd: password}})) {{
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = name;
        input.value = value;
        form.appendChild(input);
      }}
      document.body.appendChild(form);
      form.submit();
    }} catch (_) {{
      showError("لا يوجد متجر مرتبط بهذا البريد الإلكتروني.");
    }}
  }}, true);
}})();
</script>
"""
        html = html.replace("</head>", bridge + "\n</head>", 1)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_landing_asset(self, filename: str):
        path = LANDING_ASSETS / Path(filename).name
        if not path.is_file():
            return self._send(404, {"detail": "not found"})
        body = path.read_bytes()
        content_type = (
            "image/png"
            if path.suffix.lower() == ".png"
            else "application/octet-stream"
        )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        request_path = urlparse(self.path).path
        if request_path == "/auth/google/merchant":
            try:
                return self._redirect(social_auth.google_authorize_url())
            except social_auth.SocialAuthError as exc:
                return self._send(502, {"detail": "external service unavailable"})
        if request_path in ("/merchant-access", "/merchant-access.html"):
            return self._redirect(
                f"{pv.PUBLIC_SCHEME}://{pv.BASE_DOMAIN}/login"
            )
        if request_path == "/login" and not self._is_tenant_host():
            return self._send_unified_merchant_login()
        if request_path == "/merchant-login":
            if not self._is_tenant_host():
                return self._redirect("/login")
            # Use the site's native Frappe login instead of maintaining a
            # second password form with different styling and behaviour.
            query = parse_qs(urlparse(self.path).query)
            email = (query.get("email") or [""])[0].strip()
            params = {"redirect-to": "/desk"}
            if email:
                params["email"] = email
            return self._redirect("/login?" + urlencode(params))
        if request_path == "/me":
            return self._redirect(
                "/desk" if self._is_tenant_host() else "/login"
            )
        if request_path in ("/customer-login", "/customer-login.html"):
            return self._send_html(CUSTOMER_LOGIN_HTML)
        if request_path in (
            "/customer-signup",
            "/customer-signup.html",
        ):
            return self._send_html(CUSTOMER_SIGNUP_HTML)
        if request_path in (
            "/customer-account",
            "/customer-account.html",
        ):
            return self._send_html(CUSTOMER_ACCOUNT_HTML)
        if request_path in (
            "/customer-orders",
            "/customer-orders.html",
        ):
            return self._send_html(CUSTOMER_ORDERS_HTML)
        if request_path in ("/signup", "/signup.html"):
            if self._is_tenant_host():
                # `/signup` is reserved for merchant/platform registration.
                # Store customers use the explicit `/customer-signup` route.
                return self._redirect(
                    f"{pv.PUBLIC_SCHEME}://{pv.BASE_DOMAIN}/signup"
                )
            return self._send_html(SIGNUP_HTML)
        if request_path == "/":
            return self._send_html(LANDING_HTML)
        if request_path.startswith("/landing-assets/"):
            return self._send_landing_asset(request_path.rsplit("/", 1)[-1])
        if request_path in ("/register", "/register.html"):
            return self._send_html(SIGNUP_HTML)
        if request_path in ("/onboarding", "/onboarding.html", "/setup"):  # الخطوة 2: إعداد المتجر
            return self._send_html(ONBOARDING_HTML)
        if request_path == "/health":
            return self._send(200, {
                "status": "ok",
                "service": "dukkani-provisioning",
                "required_routes": [
                    "/resolve",
                    "/shop/products",
                    "/shop/order",
                    "/shop/review",
                    "/shop/customer-login",
                    "/auth/google/merchant",
                    "/auth/apple/exchange",
                ],
            })
        if request_path == "/resolve":   # الموبايل: إيميل → subdomain
            email = (parse_qs(urlparse(self.path).query).get("email", [""])[0] or "").strip()
            if not email:
                return self._send(400, {"detail": "email مطلوب"})
            try:
                sub = resolver.resolve(email)
            except Exception as exc:                       # noqa: BLE001
                return self._send(502, {"detail": "request failed"})
            if not sub:
                return self._send(404, {"detail": "لا يوجد متجر مرتبط بهذا البريد"})
            return self._send(200, {"subdomain": sub})
        if request_path.startswith("/shop/reverse-geocode"):
            params = parse_qs(urlparse(self.path).query)
            lat = (params.get("lat", [""])[0] or "").strip()
            lng = (params.get("lng", [""])[0] or "").strip()
            if not lat or not lng:
                return self._send(400, {"detail": "lat و lng مطلوبان"})
            try:
                return self._send(200, shopapi.reverse_geocode(lat, lng))
            except Exception as exc:                       # noqa: BLE001
                return self._send(502, {"detail": "request failed"})
        if request_path.startswith("/shop/products"):        # واجهة المتجر: عرض المنتجات
            store = (parse_qs(urlparse(self.path).query).get("store", [""])[0] or "").lower()
            if not store:
                return self._send(400, {"detail": "store مطلوب"})
            try:
                return self._send(200, shopapi.list_products(store))
            except Exception as exc:                       # noqa: BLE001
                return self._send(500, {"detail": "request failed"})
        if request_path == "/shop/customer-orders":
            params = parse_qs(urlparse(self.path).query)
            store = (params.get("store", [""])[0] or "").strip().lower()
            email = (params.get("email", [""])[0] or "").strip().lower()
            if not store or not email:
                return self._send(400, {"detail": "store و email مطلوبان"})
            try:
                return self._send(200, shopapi.customer_orders(store, email))
            except Exception as exc:                       # noqa: BLE001
                return self._send(500, {"detail": "request failed"})
        if request_path == "/shop/track-order":
            params = parse_qs(urlparse(self.path).query)
            store = (params.get("store", [""])[0] or "").strip().lower()
            order = (params.get("order", [""])[0] or "").strip()
            email = (params.get("email", [""])[0] or "").strip().lower()
            if not store or not order or not email:
                return self._send(400, {"detail": "بيانات تتبع الطلب ناقصة"})
            try:
                return self._send(200, shopapi.track_order(store, order, email))
            except Exception as exc:                       # noqa: BLE001
                return self._send(500, {"detail": "request failed"})
        if request_path == "/tenants":
            return self._send(200, public_tenants(pv.list_tenants()))
        if request_path.startswith("/tenants/"):
            sub = request_path.split("/tenants/", 1)[1].strip("/").lower()
            rec = pv.get_status(sub)
            if rec:
                return self._send(200, public_tenant(rec))
            return self._send(404, {"detail": "التاجر غير موجود"})
        return self._send(404, {"detail": "غير موجود"})

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _read_form(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8", "replace")
        return {key: values[0] for key, values in parse_qs(raw).items()}

    def do_POST(self):
        request_path = urlparse(self.path).path
        if request_path == "/merchant-login" and self._is_tenant_host():
            data = self._read_form()
            email = (data.get("usr") or "").strip().lower()
            password = data.get("pwd") or ""
            expected_store = self._host().split(".", 1)[0]
            try:
                resolved_store = resolver.resolve(email)
            except Exception:
                resolved_store = None
            if not email or not password or resolved_store != expected_store:
                return self._redirect(
                    f"{pv.PUBLIC_SCHEME}://{pv.BASE_DOMAIN}/login?"
                    + urlencode({"error": "invalid", "email": email})
                )
            payload = urlencode({"usr": email, "pwd": password}).encode("utf-8")
            request = Request(
                f"{pv.PUBLIC_SCHEME}://{self._host()}/api/method/login",
                data=payload,
                method="POST",
                headers={
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-For": self.client_address[0],
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                },
            )
            try:
                with urlopen(request, timeout=25) as response:
                    response.read()
                    cookies = response.headers.get_all("Set-Cookie") or []
            except (HTTPError, URLError, TimeoutError):
                return self._redirect(
                    f"{pv.PUBLIC_SCHEME}://{pv.BASE_DOMAIN}/login?"
                    + urlencode({"error": "invalid", "email": email})
                )
            self.send_response(302)
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Location", "/desk")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if request_path == "/auth/google/exchange":
            try:
                data = self._read_json()
                result = social_auth.exchange_google_ticket(
                    str(data.get("ticket") or "")
                )
                return self._send(200, result)
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"detail": "JSON غير صالح"})
            except social_auth.SocialAuthError as exc:
                return self._send(401, {"detail": "authentication failed"})
            except Exception:
                return self._send(500, {"detail": "تعذّر تسجيل الدخول عبر Google."})
        if request_path == "/auth/apple/exchange":
            try:
                data = self._read_json()
                result = social_auth.exchange_apple_token(
                    str(data.get("identity_token") or ""),
                    raw_nonce=str(data.get("raw_nonce") or ""),
                    full_name=str(data.get("full_name") or ""),
                )
                return self._send(200, result)
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"detail": "JSON غير صالح"})
            except social_auth.SocialAuthError as exc:
                return self._send(401, {"detail": "authentication failed"})
            except Exception:
                return self._send(500, {"detail": "تعذّر تسجيل الدخول عبر Apple."})
        if request_path == "/register":
            return self._register()
        if request_path in ("/shop/customer-register", "/shop/customer-signup"):
            store = (
                parse_qs(urlparse(self.path).query).get("store", [""])[0] or ""
            ).strip().lower()
            try:
                data = self._read_json()
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"detail": "JSON غير صالح"})
            if not store:
                return self._send(400, {"detail": "store مطلوب"})
            try:
                result = shopapi.register_customer(store, data)
                return self._send(
                    201 if result.get("created") else 422,
                    result,
                )
            except Exception as exc:                       # noqa: BLE001
                return self._send(500, {"detail": "request failed"})
        if request_path == "/shop/customer-login":
            store = (
                parse_qs(urlparse(self.path).query).get("store", [""])[0] or ""
            ).strip().lower()
            try:
                data = self._read_json()
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"detail": "JSON غير صالح"})
            if not store:
                return self._send(400, {"detail": "store مطلوب"})
            try:
                result = shopapi.login_customer(store, data)
                return self._send(
                    200 if result.get("authenticated") else 401,
                    result,
                )
            except Exception as exc:                       # noqa: BLE001
                return self._send(500, {"detail": "request failed"})
        if self.path.startswith("/shop/order"):           # واجهة المتجر: إتمام طلب الزبون
            store = (parse_qs(urlparse(self.path).query).get("store", [""])[0] or "").lower()
            try:
                data = self._read_json()
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"detail": "JSON غير صالح"})
            if not store or not data.get("items"):
                return self._send(400, {"detail": "بيانات الطلب ناقصة"})
            try:
                return self._send(201, shopapi.place_order(store, data))
            except Exception as exc:                       # noqa: BLE001
                return self._send(500, {"detail": "request failed"})
        if self.path.startswith("/shop/review"):          # واجهة المتجر: تقييم منتج
            store = (parse_qs(urlparse(self.path).query).get("store", [""])[0] or "").lower()
            try:
                data = self._read_json()
            except (ValueError, json.JSONDecodeError):
                return self._send(400, {"detail": "JSON غير صالح"})
            if not store or not data.get("code"):
                return self._send(400, {"detail": "بيانات التقييم ناقصة"})
            try:
                return self._send(201, shopapi.add_review(store, data))
            except Exception as exc:                       # noqa: BLE001
                return self._send(500, {"detail": "request failed"})
        if self.path != "/tenants":
            return self._send(404, {"detail": "غير موجود"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"detail": "JSON غير صالح"})

        sub, err = _valid_subdomain(data.get("subdomain", ""))
        if err:
            return self._send(422, {"detail": err})
        name = (data.get("merchant_name") or "").strip()
        if len(name) < 2:
            return self._send(422, {"detail": "اسم المتجر قصير جداً."})
        email = (data.get("email") or "").strip()
        if "@" not in email:
            return self._send(422, {"detail": "بريد إلكتروني غير صالح."})
        password = data.get("password") or ""
        if len(password) < 6:
            return self._send(422, {"detail": "كلمة المرور 6 أحرف على الأقل."})
        country = (data.get("country") or "Saudi Arabia").strip()
        if country not in {c["country"] for c in COUNTRY_BY_CODE.values()}:
            country = "Saudi Arabia"

        existing = pv.get_status(sub)
        if existing and existing.get("status") == "ready":
            return self._send(409, {"detail": f"النطاق '{sub}' مستخدم بالفعل (ready)."})
        if (
            existing
            and existing.get("status") in {"provisioning", "pending"}
            and (existing.get("email") or "").lower() != email.lower()
        ):
            return self._send(
                409,
                {"detail": f"النطاق '{sub}' مستخدم بالفعل ({existing['status']})."},
            )

        # الخطوة 2: استلام الطلب وبدء التجهيز في الخلفية
        site = f"{sub}.{pv.BASE_DOMAIN}"
        public_url = f"{pv.PUBLIC_SCHEME}://{site}" + (f":{pv.PORT}" if pv.BASE_DOMAIN == "localhost" else "")
        pv.set_status(sub, status="pending", merchant_name=name,
                      email=email, country=country, url=public_url)
        pv.start_provision(sub, name, email, password, country)

        return self._send(202, {
            "subdomain": sub,
            "status": "pending",
            "message": "بدأ تجهيز متجرك — تابع الحالة عبر GET /tenants/{subdomain}",
            "status_url": f"/tenants/{sub}",
            "store_url": public_url,
        })

    def _register(self):
        """الخطوة 1 (زي دكاني): إنشاء حساب التاجر — اسم + إيميل + كود دولة + جوال.
        كود الدولة بيحدّد الجنسية/الدولة/العملة (سعودي/مصري/سوداني). لسه بدون تجهيز
        متجر — ده بيجي في الخطوة 2 (إعداد المتجر)."""
        try:
            data = self._read_json()
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"detail": "JSON غير صالح"})

        full_name = (data.get("full_name") or "").strip()
        email = (data.get("email") or "").strip()
        phone = (data.get("phone") or "").strip()
        code = str(data.get("country_code") or "").strip()

        if len(full_name) < 2:
            return self._send(422, {"detail": "اكتب الاسم الكامل."})
        if "@" not in email:
            return self._send(422, {"detail": "بريد إلكتروني غير صالح."})
        if code not in COUNTRY_BY_CODE:
            return self._send(422, {"detail": "كود دولة غير مدعوم."})
        if not phone.isdigit() or len(phone) < 6:
            return self._send(422, {"detail": "رقم جوال غير صالح."})

        info = COUNTRY_BY_CODE[code]
        account = {
            "full_name": full_name, "email": email,
            "phone": f"+{code}{phone}", "country_code": code,
            "country": info["country"], "currency": info["currency"],
            "status": "registered",
        }
        # تخزين بسيط للحساب (ملف JSON) — منع تكرار نفس الإيميل
        accounts = {}
        if ACCOUNTS_FILE.exists():
            try:
                accounts = json.loads(ACCOUNTS_FILE.read_text("utf-8"))
            except (ValueError, json.JSONDecodeError):
                accounts = {}
        existing_account = accounts.get(email.lower())
        if existing_account:
            same_identity = (
                existing_account.get("phone") == account["phone"]
                and existing_account.get("country_code") == code
            )
            has_ready_store = any(
                (tenant.get("email") or "").lower() == email.lower()
                and tenant.get("status") == "ready"
                for tenant in pv.list_tenants()
            )
            if same_identity and not has_ready_store:
                return self._send(200, {
                    "status": "registered",
                    "country": existing_account.get("country") or info["country"],
                    "currency": existing_account.get("currency") or info["currency"],
                    "message": "تم استرجاع الحساب — أكمل إعداد المتجر.",
                    "next": "/setup",
                })
            return self._send(409, {"detail": "البريد الإلكتروني مسجّل بالفعل."})
        accounts[email.lower()] = account
        ACCOUNTS_FILE.write_text(json.dumps(accounts, ensure_ascii=False, indent=2), "utf-8")

        return self._send(201, {
            "status": "registered",
            "country": info["country"],
            "currency": info["currency"],
            "message": "تم إنشاء الحساب — الخطوة الجاية: إعداد المتجر.",
            "next": "/setup",
        })

    def log_message(self, fmt, *args):   # هدوء في السجلّ
        print(f"[api] {self.address_string()} {fmt % args}")


def _auto_sync_loop():
    """يشغّل مزامنة لوحة الأدمن دورياً في الخلفية (يحدّث أرقام التجّار تلقائياً).
    يوقف مؤقتاً لو فيه متجر بيتجهّز حالياً — عشان التجهيز يخلص أسرع."""
    while True:
        time.sleep(SYNC_EVERY)
        # تخطّي المزامنة أثناء تجهيز متجر (عشان ما تزاحمش الموارد)
        busy = any(t.get("status") in ("provisioning", "pending")
                   for t in pv.list_tenants())
        if busy:
            print("[auto-sync] متجر بيتجهّز — تأجيل المزامنة")
            continue
        try:
            subprocess.run([sys.executable, str(SYNC_SCRIPT)],
                           capture_output=True, timeout=300,
                           env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
            print("[auto-sync] تم تحديث لوحة الأدمن")
        except Exception as exc:                                # noqa: BLE001
            print(f"[auto-sync] تخطّي: {exc}")


def _deploy_pages():
    """Publish only shared platform pages inside Frappe.

    Merchant signup is served by the central API. Copying it into Frappe's
    shared ``www/signup.html`` leaks the merchant flow into every tenant.
    """
    www = "/home/frappe/frappe-bench/apps/frappe/frappe/www"
    done = []
    # /shop belongs to the merchant's selected Builder page. Deploying the
    # legacy static shop.html here would shadow Builder's route on every site.
    for f in ("platform",):
        p = API_DIR / (f + ".html")
        if p.exists():
            try:
                subprocess.run(["docker", "exec", "-i", "dukkani-backend-1", "bash", "-c",
                                "cat > " + www + "/" + f + ".html"],
                               input=p.read_bytes(), timeout=30)
                done.append(f)
            except Exception:
                pass
    try:
        subprocess.run(["docker", "exec", "dukkani-backend-1", "bench", "--site", "admin.localhost",
                        "clear-website-cache"], capture_output=True, timeout=60)
    except Exception:
        pass
    print("[deploy] اتنشرت الصفحات: " + ", ".join(done))


class DukkaniHTTPServer(ThreadingHTTPServer):
    """Keep the public gateway responsive while provisioning jobs are running."""

    request_queue_size = 128
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"==> Dukkani Provisioning API (stdlib) على http://0.0.0.0:{PORT}")
    print(f"==> مزامنة تلقائية للأدمن كل {SYNC_EVERY} ثانية")
    _deploy_pages()
    resumed = pv.resume_pending_jobs()
    if resumed:
        print(f"[provisioning] تم استكمال {resumed} متجر بعد إعادة التشغيل")
    threading.Thread(target=_auto_sync_loop, daemon=True).start()
    DukkaniHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
