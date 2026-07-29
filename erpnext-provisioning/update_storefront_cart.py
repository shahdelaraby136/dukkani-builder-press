"""Update the shared Builder storefront cart script without touching page designs."""

import os

import frappe


name = "Dukkani Storefront Commerce"
path = os.environ.get("STOREFRONT_CART_PATH", "/tmp/storefront_cart.js")
with open(path, encoding="utf-8") as source:
    script = source.read()

if not frappe.db.exists("Builder Client Script", name):
    frappe.throw(f"Missing Builder Client Script: {name}")

doc = frappe.get_doc("Builder Client Script", name)
doc.script_type = "JavaScript"
doc.script = script
doc.save(ignore_permissions=True)
frappe.db.commit()
frappe.clear_cache()
print("DUKKANI_STOREFRONT_CART_UPDATED")
