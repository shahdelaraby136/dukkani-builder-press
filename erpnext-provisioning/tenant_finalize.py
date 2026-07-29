"""Personalize a Dukkani tenant restored from a country template snapshot."""

import os

import frappe


MERCHANT_NAME = os.environ["MERCHANT_NAME"].strip()
MERCHANT_EMAIL = os.environ["MERCHANT_EMAIL"].strip().lower()
MERCHANT_PASSWORD = os.environ["MERCHANT_PASSWORD"]
COUNTRY = os.environ["MERCHANT_COUNTRY"].strip()

LOCALE = {
    "Saudi Arabia": {"currency": "SAR", "timezone": "Asia/Riyadh"},
    "Egypt": {"currency": "EGP", "timezone": "Africa/Cairo"},
    "Sudan": {"currency": "SDG", "timezone": "Africa/Khartoum"},
}
locale = LOCALE[COUNTRY]


def personalize_company():
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not company:
        frappe.throw("Template has no default company")
    if company != MERCHANT_NAME:
        if frappe.db.exists("Company", MERCHANT_NAME):
            frappe.throw("Store company already exists")
        frappe.rename_doc(
            "Company",
            company,
            MERCHANT_NAME,
            force=True,
        )
        company = MERCHANT_NAME

    frappe.db.set_value("Company", company, {
        "company_name": MERCHANT_NAME,
        "country": COUNTRY,
        "default_currency": locale["currency"],
    })
    defaults = frappe.get_doc("Global Defaults")
    defaults.default_company = company
    defaults.country = COUNTRY
    defaults.default_currency = locale["currency"]
    defaults.save(ignore_permissions=True)

    settings = frappe.get_doc("System Settings")
    settings.country = COUNTRY
    settings.time_zone = locale["timezone"]
    settings.setup_complete = 1
    settings.save(ignore_permissions=True)
    frappe.db.sql("UPDATE `tabInstalled Application` SET is_setup_complete=1")

    for price_list in frappe.get_all(
        "Price List", filters={"selling": 1}, pluck="name"
    ):
        frappe.db.set_value(
            "Price List", price_list, "currency", locale["currency"]
        )


def create_owner():
    profile = "Dukkani Store Owner"
    roles = (
        [row.role for row in frappe.get_doc("Role Profile", profile).roles]
        if frappe.db.exists("Role Profile", profile)
        else ["Sales Manager", "Stock Manager", "Accounts Manager", "Item Manager"]
    )
    exists = frappe.db.exists("User", MERCHANT_EMAIL)
    user = (
        frappe.get_doc("User", MERCHANT_EMAIL)
        if exists
        else frappe.new_doc("User")
    )
    if not exists:
        parts = MERCHANT_NAME.split()
        user.email = MERCHANT_EMAIL
        user.first_name = parts[0] if parts else MERCHANT_NAME
        user.last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
        user.send_welcome_email = 0
    user.enabled = 1
    user.user_type = "System User"
    user.language = "ar"
    user.time_zone = locale["timezone"]
    if MERCHANT_PASSWORD:
        user.new_password = MERCHANT_PASSWORD
    if user.meta.has_field("role_profile_name"):
        user.role_profile_name = profile
    existing_roles = {row.role for row in user.get("roles", [])}
    for role in roles:
        if role not in existing_roles and frappe.db.exists("Role", role):
            user.append("roles", {"role": role})
    user.flags.ignore_permissions = True
    user.flags.ignore_password_policy = True
    user.save(ignore_permissions=True)
    if not frappe.db.exists(
        "Has Role",
        {"parent": MERCHANT_EMAIL, "parenttype": "User", "role": "Merchant Owner"},
    ):
        frappe.get_doc({
            "doctype": "Has Role",
            "parent": MERCHANT_EMAIL,
            "parenttype": "User",
            "parentfield": "roles",
            "role": "Merchant Owner",
        }).insert(ignore_permissions=True)


def publish_default_storefront():
    """Make the Boutique starter the live store for a brand-new tenant."""
    page_name = (
        frappe.db.get_value("Builder Page", {"route": "shop"}, "name")
        or frappe.db.get_value(
            "Builder Page", {"route": "themes/boutique"}, "name"
        )
    )
    if not page_name:
        frappe.throw("Template has no Boutique storefront")
    # Builder's document save hook recompiles the entire page and adds roughly
    # 30 seconds. The snapshot already contains compiled blocks/scripts, so
    # publishing only needs these persisted route fields.
    frappe.db.set_value(
        "Builder Page",
        page_name,
        {"route": "shop", "published": 1},
        update_modified=True,
    )
    frappe.db.set_single_value("Website Settings", "home_page", "shop")


frappe.flags.in_import = True
frappe.flags.mute_emails = True
personalize_company()
create_owner()
publish_default_storefront()
frappe.db.commit()
frappe.clear_cache()
print("Dukkani tenant personalized successfully")
