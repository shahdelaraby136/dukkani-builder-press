"""Refresh Traefik routes for all registered and legacy tenant storefronts."""

import os
import json
import re
import provisioner
import resolver


if provisioner.BASE_DOMAIN == "localhost":
    raise RuntimeError(
        "Set DUKKANI_BASE_DOMAIN=dukani.ai before refreshing production routes"
    )


def write_public_route(subdomain):
    host = f"{subdomain}.{provisioner.BASE_DOMAIN}"
    key = re.sub(r"[^a-z0-9-]", "-", subdomain.lower())
    canonical = f"store-{key}-canonical"
    builder_canonical = f"store-{key}-builder-canonical"
    home = f"store-{key}-home"
    config = {
        "http": {
            "middlewares": {
                canonical: {"redirectRegex": {
                    "regex": rf"^https?://{re.escape(host)}/shop/?$",
                    "replacement": f"https://{host}/",
                    "permanent": True,
                }},
                builder_canonical: {"redirectRegex": {
                    "regex": rf"^https?://{re.escape(host)}/builder/$",
                    "replacement": f"https://{host}/builder",
                    "permanent": True,
                }},
                home: {"replacePath": {"path": "/shop"}},
            },
            "routers": {
                home: {
                    "rule": f"Host(`{host}`) && Path(`/`)",
                    "entryPoints": ["websecure"], "priority": 120,
                    "middlewares": [home], "service": "dukkani-web@file",
                    "tls": {"certResolver": "letsencrypt"},
                },
                canonical: {
                    "rule": f"Host(`{host}`) && (Path(`/shop`) || Path(`/shop/`))",
                    "entryPoints": ["websecure"], "priority": 110,
                    "middlewares": [canonical], "service": "dukkani-web@file",
                    "tls": {"certResolver": "letsencrypt"},
                },
                builder_canonical: {
                    "rule": f"Host(`{host}`) && Path(`/builder/`)",
                    "entryPoints": ["websecure"], "priority": 115,
                    "middlewares": [builder_canonical], "service": "dukkani-web@file",
                    "tls": {"certResolver": "letsencrypt"},
                },
                f"store-{key}-api": {
                    "rule": f"Host(`{host}`) && (Path(`/merchant-access`) || Path(`/merchant-access.html`) || Path(`/merchant-login`) || Path(`/me`) || Path(`/customer-login`) || Path(`/customer-login.html`) || Path(`/customer-account`) || Path(`/customer-account.html`) || Path(`/customer-orders`) || Path(`/customer-orders.html`) || Path(`/signup`) || Path(`/signup.html`) || Path(`/customer-signup`) || Path(`/customer-signup.html`) || PathPrefix(`/shop/customer-register`) || PathPrefix(`/shop/customer-login`) || PathPrefix(`/shop/customer-orders`) || PathPrefix(`/shop/products`) || PathPrefix(`/shop/reverse-geocode`) || PathPrefix(`/shop/order`) || PathPrefix(`/shop/review`))",
                    "entryPoints": ["websecure"], "priority": 100,
                    "service": "dukkani-api@file", "tls": {"certResolver": "letsencrypt"},
                },
                f"store-{key}-web": {
                    "rule": f"Host(`{host}`)", "entryPoints": ["websecure"],
                    "service": "dukkani-web@file", "tls": {"certResolver": "letsencrypt"},
                },
            },
        },
    }
    provisioner.TRAEFIK_ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    target = provisioner.TRAEFIK_ROUTES_DIR / f"store-{key}.yml"
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)


subdomains = {
    (tenant.get("subdomain") or "").strip().lower()
    for tenant in provisioner.list_tenants()
    if (tenant.get("subdomain") or "").strip()
}
suffix = "." + provisioner.BASE_DOMAIN
for site_name, _config in resolver._site_configs():
    if site_name.endswith(suffix):
        subdomains.add(site_name[: -len(suffix)])
subdomains.update(
    value.strip().lower()
    for value in os.environ.get("DUKKANI_LEGACY_SUBDOMAINS", "noorelhaya").split(",")
    if value.strip()
)

updated = []
for subdomain in sorted(subdomains):
    if subdomain in {"", "www"}:
        continue
    write_public_route(subdomain)
    updated.append(subdomain)

print("DUKKANI_PUBLIC_ROUTES_UPDATED=" + ",".join(updated))
