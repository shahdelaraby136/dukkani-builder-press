"""Install hooks for Dukani Marketing."""

import frappe


def after_install() -> None:
    """Create the least-privilege role used by the app, idempotently."""
    role_name = "Dukani Marketing User"
    if not frappe.db.exists("Role", role_name):
        frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": role_name,
                "desk_access": 1,
                "is_custom": 1,
            }
        ).insert(ignore_permissions=True)
