"""Remove tenant-specific data before taking a provisioning template backup."""

import os

import frappe


TEMPLATE_OWNER = os.environ["TEMPLATE_OWNER"].strip().lower()


def delete_documents(doctype):
    if not frappe.db.exists("DocType", doctype):
        return
    for name in frappe.get_all(doctype, pluck="name"):
        frappe.delete_doc(
            doctype,
            name,
            force=True,
            ignore_permissions=True,
        )


for doctype in (
    "Email Account",
    "Email Queue",
    "Communication",
    "Notification Log",
    "OAuth Bearer Token",
    "OAuth Authorization Code",
    "Integration Request",
    "Error Log",
    "Activity Log",
    "Access Log",
):
    delete_documents(doctype)

if frappe.db.exists("User", TEMPLATE_OWNER):
    frappe.delete_doc(
        "User",
        TEMPLATE_OWNER,
        force=True,
        ignore_permissions=True,
    )

frappe.db.delete("Sessions")
frappe.db.commit()
frappe.clear_cache()
print("Dukkani fast template sanitized")
