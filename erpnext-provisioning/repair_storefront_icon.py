"""Restore the tenant Desk shortcut without changing storefront content."""

import frappe


LABEL = "\u0648\u0627\u062c\u0647\u0629 \u0627\u0644\u0645\u062a\u062c\u0631"
ALIASES = [
    "\u0645\u062a\u062c\u0631\u064a",
    LABEL,
    "\u0627\u0644\u0645\u062a\u062c\u0631 \u0627\u0644\u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a",
]
VALUES = {
    "label": LABEL,
    "icon_type": "App",
    "link_type": "External",
    "app": "erpnext",
    "logo_url": "/assets/erpnext/images/erpnext-logo.svg",
    "link": "/",
    "hidden": 0,
    "idx": 90,
}


def repair_storefront_icon():
    if not frappe.db.exists("Builder Page", {"route": "shop"}):
        raise RuntimeError("The site has no published Builder storefront at /shop")

    name = (
        frappe.db.get_value("Desktop Icon", {"link": "/shop"}, "name")
        or frappe.db.get_value("Desktop Icon", {"label": ["in", ALIASES]}, "name")
    )
    if name:
        frappe.db.set_value("Desktop Icon", name, VALUES)
    else:
        doc = frappe.get_doc({"doctype": "Desktop Icon", **VALUES})
        doc.insert(ignore_permissions=True)
        name = doc.name
    frappe.db.commit()
    print(f"DUKKANI_STOREFRONT_ICON_READY {name}")


repair_storefront_icon()
