"""Serve an existing tenant's /shop Builder page at the bare store domain."""

import frappe


MY_STORE = "\u0645\u062a\u062c\u0631\u064a"
STOREFRONT = "\u0648\u0627\u062c\u0647\u0629 \u0627\u0644\u0645\u062a\u062c\u0631"
ONLINE_STORE = "\u0627\u0644\u0645\u062a\u062c\u0631 \u0627\u0644\u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a"

settings = frappe.get_single("Website Settings")
settings.home_page = "shop"
settings.save(ignore_permissions=True)
shop_icon = (
    frappe.db.get_value("Desktop Icon", {"link": "/shop"}, "name")
    or frappe.db.get_value("Desktop Icon", {"label": ["in", [MY_STORE, STOREFRONT, ONLINE_STORE]]}, "name")
)
if shop_icon:
    frappe.db.set_value("Desktop Icon", shop_icon, "link", "/")
    frappe.db.set_value("Desktop Icon", shop_icon, "label", STOREFRONT)
frappe.db.commit()
frappe.clear_cache()
print("DUKKANI_PUBLIC_STORE_HOME_OK")
