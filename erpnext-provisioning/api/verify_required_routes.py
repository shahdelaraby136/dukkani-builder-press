"""Fail deployment checks when login/signup/landing contracts disappear."""
import inspect
from pathlib import Path
import server
import shopapi


get_source = inspect.getsource(server.Handler.do_GET)
post_source = inspect.getsource(server.Handler.do_POST)
deploy_source = inspect.getsource(server._deploy_pages)
required_get = (
    'request_path == "/resolve"',
    "resolver.resolve(email)",
    'request_path == "/auth/google/merchant"',
    '"/merchant-access", "/merchant-access.html"',
    '"/signup", "/signup.html"',
    "self._is_tenant_host()",
    "CUSTOMER_SIGNUP_HTML",
    "LANDING_HTML",
)
required_post = (
    'request_path == "/auth/google/exchange"',
    'request_path == "/register"',
    'request_path in ("/shop/customer-register", "/shop/customer-signup")',
    'self.path != "/tenants"',
)
missing = [fragment for fragment in required_get if fragment not in get_source]
missing += [fragment for fragment in required_post if fragment not in post_source]
if missing:
    raise SystemExit("Missing auth-flow implementation: " + ", ".join(missing))
if '201 if result.get("created") else 422' not in post_source:
    raise SystemExit("Customer registration reports failures as successful HTTP 201")
if '200 if result.get("authenticated") else 401' not in post_source:
    raise SystemExit("Customer login reports failed credentials as successful HTTP 200")
if '"signup"' in deploy_source:
    raise SystemExit("Central merchant signup must not be copied into shared Frappe www")

customer_login_source = shopapi.CUSTOMER_LOGIN_CODE
required_customer_guards = (
    'user.user_type == "Website User"',
    '"Customer" in roles',
    "merchant_roles",
    "not roles.intersection(merchant_roles)",
)
missing_customer_guards = [
    fragment
    for fragment in required_customer_guards
    if fragment not in customer_login_source
]
if missing_customer_guards:
    raise SystemExit(
        "Customer login can accept merchant identities: "
        + ", ".join(missing_customer_guards)
    )

api_dir = Path(server.__file__).resolve().parent
required_files = (
    "landing/index.html",
    "signup.html",
    "customer-signup.html",
    "customer-login.html",
    "social_auth.py",
)
missing_files = [name for name in required_files if not (api_dir / name).is_file()]
if missing_files:
    raise SystemExit("Missing auth-flow files: " + ", ".join(missing_files))
print("REQUIRED_AUTH_FLOW_OK")
