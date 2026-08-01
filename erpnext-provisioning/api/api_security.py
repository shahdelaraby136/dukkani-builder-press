from urllib.parse import urlparse


PUBLIC_TENANT_FIELDS = (
    "subdomain",
    "status",
    "url",
    "provisioning_step",
    "elapsed_seconds",
    "storefront_status",
)


def public_tenant(record):
    if not record:
        return None
    return {field: record[field] for field in PUBLIC_TENANT_FIELDS if field in record}


def public_tenants(records):
    return [public_tenant(record) for record in records]


def allowed_origin(origin, base_domain):
    if not origin:
        return None
    parsed = urlparse(origin)
    host = (parsed.hostname or "").lower()
    domain = base_domain.strip().lower()
    if domain == "localhost":
        return origin if host in {"localhost", "127.0.0.1"} else None
    if parsed.scheme != "https":
        return None
    if host == domain or host.endswith("." + domain):
        return origin
    return None
