import frappe

from dukkani_marketing.validation import next_status, validate_draft_input


@frappe.whitelist()
def get_current_tenant():
    """Return the tenant from the authenticated Frappe site, never from request data."""
    tenant = getattr(frappe.local, "site", None)
    if not tenant:
        frappe.throw("Tenant site is not available", frappe.ValidationError)
    return tenant


def require_marketing_access():
    if frappe.session.user == "Guest":
        frappe.throw("Login is required", frappe.PermissionError)
    if not frappe.has_role("Dukani Marketing User") and not frappe.has_role("System Manager"):
        frappe.throw("Dukani Marketing User role is required", frappe.PermissionError)


@frappe.whitelist()
def create_content_draft(title, body, channel="internal"):
    """Create a tenant-scoped draft; publishing is deliberately not available yet."""
    require_marketing_access()
    values = validate_draft_input(title=title, body=body, channel=channel)
    doc = frappe.get_doc(
        {
            "doctype": "Dukani Marketing Content",
            "title": values["title"],
            "body": values["body"],
            "channel": values["channel"],
            "status": "Draft",
            "tenant_site": get_current_tenant(),
            "created_by_user": frappe.session.user,
        }
    )
    doc.insert(ignore_permissions=False)
    return {"name": doc.name, "status": doc.status, "tenant_site": doc.tenant_site}


@frappe.whitelist()
def list_content_drafts(limit=50):
    """List drafts for the current tenant only."""
    require_marketing_access()
    try:
        limit = min(max(int(limit), 1), 100)
    except (TypeError, ValueError):
        frappe.throw("limit must be an integer", frappe.ValidationError)
    return frappe.get_list(
        "Dukani Marketing Content",
        filters={"tenant_site": get_current_tenant(), "status": "Draft"},
        fields=["name", "title", "channel", "status", "created_by_user", "creation"],
        order_by="creation desc",
        limit_page_length=limit,
    )


def get_tenant_content(name):
    doc = frappe.get_doc("Dukani Marketing Content", name)
    if doc.tenant_site != get_current_tenant():
        frappe.throw("Content belongs to another tenant", frappe.PermissionError)
    return doc


@frappe.whitelist()
def submit_content_draft(name):
    require_marketing_access()
    doc = get_tenant_content(name)
    doc.status = next_status(doc.status, "submit")
    doc.save(ignore_permissions=False)
    return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def approve_content_draft(name):
    require_marketing_access()
    if not frappe.has_role("System Manager"):
        frappe.throw("Only a System Manager can approve content", frappe.PermissionError)
    doc = get_tenant_content(name)
    doc.status = next_status(doc.status, "approve")
    doc.save(ignore_permissions=False)
    return {"name": doc.name, "status": doc.status}


@frappe.whitelist()
def reject_content_draft(name):
    require_marketing_access()
    if not frappe.has_role("System Manager"):
        frappe.throw("Only a System Manager can reject content", frappe.PermissionError)
    doc = get_tenant_content(name)
    doc.status = next_status(doc.status, "reject")
    doc.save(ignore_permissions=False)
    return {"name": doc.name, "status": doc.status}
