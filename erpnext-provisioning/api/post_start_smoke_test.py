"""Non-destructive production smoke test run after every Dukkani API restart."""
import json
import os
import re
import time
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


BASE_URL = os.environ.get("DUKKANI_SMOKE_BASE_URL", "https://dukani.ai").rstrip("/")
STORE = os.environ.get("DUKKANI_SMOKE_STORE", "noorelhaya").strip().lower()
EMAIL = os.environ.get("DUKKANI_SMOKE_EMAIL", "noor@gmail.com").strip().lower()
STORE_URL = f"https://{STORE}.dukani.ai"


def fetch(path, attempts=12):
    url = path if path.startswith("http") else BASE_URL + path
    last_error = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": "Dukkani-Post-Deploy-Smoke/1.0"})
            with urlopen(request, timeout=20) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except Exception as exc:  # service/route may need a moment after restart
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1)
    raise RuntimeError(f"GET {url} failed: {last_error}")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_redirect(path):
    request = Request(
        BASE_URL + path,
        headers={"User-Agent": "Dukkani-Post-Deploy-Smoke/1.0"},
    )
    try:
        build_opener(_NoRedirect).open(request, timeout=20)
    except HTTPError as exc:
        return exc.code, exc.headers.get("Location", "")
    raise AssertionError(f"{path} did not redirect")


status, body = fetch("/health")
health = json.loads(body)
assert status == 200 and health.get("status") == "ok", f"health failed: {status} {body}"
assert "/resolve" in health.get("required_routes", []), "health does not advertise /resolve"
assert "/shop/customer-login" in health.get("required_routes", []), "health does not advertise customer login"
assert "/auth/google/merchant" in health.get("required_routes", []), "health does not advertise Google merchant auth"

status, landing_html = fetch("/")
assert status == 200, f"landing page failed: {status}"
assert "<title>دكاني —" in landing_html, "root is not serving the Dukkani landing page"
assert 'href="/login"' in landing_html, "landing page merchant login link is missing"

status, merchant_access_location = fetch_redirect("/merchant-access")
assert status == 302, f"legacy merchant access did not redirect: {status}"
assert merchant_access_location.endswith(
    "/login"
), f"legacy merchant access target is incorrect: {merchant_access_location}"

status, unified_login_html = fetch("/login")
assert status == 200, f"unified merchant login failed: {status}"
assert "form-login" in unified_login_html, "unified login is not using Frappe UI"
assert "dukkani-unified-merchant-login" in unified_login_html, "unified login routing is missing"

status, platform_signup_html = fetch("/signup")
assert status == 200, f"platform signup failed: {status}"
assert 'fetch(API + "/register"' in platform_signup_html, "platform signup account step is missing"
assert 'fetch(API + "/tenants"' in platform_signup_html, "platform signup provisioning step is missing"
assert 'href="/login"' in platform_signup_html, "platform signup login link is incorrect"
assert "/shop/customer-register" not in platform_signup_html, "platform signup leaks customer registration"

status, google_location = fetch_redirect("/auth/google/merchant")
assert status == 302, f"Google merchant auth did not redirect: {status}"
assert google_location.startswith("https://accounts.google.com/"), "Google merchant auth target is incorrect"

status, body = fetch(f"/resolve?email={quote(EMAIL)}")
resolved = json.loads(body)
assert status == 200 and resolved.get("subdomain") == STORE, f"resolve failed: {status} {body}"

status, body = fetch(f"{STORE_URL}/shop/products?store={quote(STORE)}")
catalog = json.loads(body)
items = catalog.get("items") or []
assert status == 200 and items, f"product API returned no items: {status} {body}"
for key in ("code", "name", "rate"):
    assert key in items[0], f"product contract is missing {key}"

status, shop_html = fetch(f"{STORE_URL}/shop")
assert status == 200, f"storefront failed: {status}"
assert "data-product-code=" in shop_html, "storefront has no add-to-cart product buttons"
assert "page_scripts/" in shop_html, "storefront cart script is missing"
script_match = re.search(r'src="([^"]*page_scripts/[^"]+\.js)', shop_html)
assert script_match, "storefront cart script URL is missing"
script_url = STORE_URL + quote(script_match.group(1), safe="/?:=&")
status, cart_script = fetch(script_url)
assert status == 200, f"storefront cart script failed: {status}"
assert "PRODUCT_ATTEMPTS" in cart_script, "storefront cart retry protection is missing"
assert "dukkani-products-error" in cart_script, "storefront cart error recovery UI is missing"
assert "frappe.session" not in cart_script, "storefront is leaking the ERPNext merchant session into customer auth"
assert "dukkani-customer-v2-" in cart_script, "storefront customer identity version is stale"
assert '"/customer-account"' in cart_script, "storefront account link does not use the customer-only route"
assert '"/me"' not in cart_script, "storefront customer account still points at the merchant route"
assert "nav.appendChild(link)" in cart_script, "storefront cannot add customer login when the theme has no login badge"
assert "dukkani-checkout-draft-" in cart_script, "checkout details are not preserved across customer login"
assert "/customer-login?next=checkout" in cart_script, "checkout does not require customer login at the final step"
assert 'get("resume")' in cart_script and '"checkout"' in cart_script, "checkout does not resume after customer login"

status, customer_login_html = fetch(f"{STORE_URL}/customer-login")
assert status == 200, f"customer login page failed: {status}"
assert "/shop/customer-login" in customer_login_html, "independent customer login endpoint is missing"
assert "/api/method/login" not in customer_login_html, "customer login is coupled to the merchant session"
assert "dukkani-customer-v2-" in customer_login_html, "customer login stores a stale identity format"
assert 'next==="checkout"?"/?resume=checkout"' in customer_login_html, "customer login cannot resume checkout"

status, customer_account_html = fetch(f"{STORE_URL}/customer-account")
assert status == 200, f"customer account page failed: {status}"
assert "dukkani-customer-v2-" in customer_account_html, "customer account reads a stale identity format"

status, customer_signup_html = fetch(f"{STORE_URL}/customer-signup")
assert status == 200, f"customer signup route failed: {status}"
assert "/shop/customer-register" in customer_signup_html, "customer signup route is not serving customer registration"
assert 'href="/customer-login"' in customer_signup_html, "customer signup login link is incorrect"
assert 'href="/merchant-access"' not in customer_signup_html, "customer signup leaks the merchant flow"

status, tenant_signup_html = fetch(f"{STORE_URL}/signup")
assert status == 200, f"tenant merchant signup redirect failed: {status}"
assert 'fetch(API + "/register"' in tenant_signup_html, "tenant /signup does not lead to merchant registration"
assert "/shop/customer-register" not in tenant_signup_html, "tenant /signup leaks customer registration"

status, merchant_login_html = fetch(f"{STORE_URL}/merchant-login")
assert status == 200, f"merchant login page failed: {status}"
assert 'form-login' in merchant_login_html, "merchant login is not using the native Frappe login"
assert 'login.bundle' in merchant_login_html, "merchant login is missing the native Frappe login assets"

status, tenant_access_html = fetch(f"{STORE_URL}/merchant-access")
assert status == 200, f"tenant merchant access fallback failed: {status}"
assert "dukkani-unified-merchant-login" in tenant_access_html, "tenant merchant access did not return to unified login"

print(json.dumps({
    "status": "ok", "resolve": STORE, "products": len(items),
    "storefront_cart": True, "customer_login_separate": True,
}, ensure_ascii=False))
