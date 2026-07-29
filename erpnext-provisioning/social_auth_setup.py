"""Install the central Frappe server scripts used by merchant social login.

Run on the public identity site only:
    bench --site www.dukani.ai console < social_auth_setup.py
"""

import frappe


ISSUE_TICKET_SCRIPT = r'''
user = frappe.session.user
if not user or user == "Guest":
    frappe.throw("Authentication required", frappe.AuthenticationError)

ticket = frappe.utils.generate_hash(length=64)
full_name = frappe.db.get_value("User", user, "full_name") or user
request = frappe.get_doc({
    "doctype": "Integration Request",
    "integration_request_service": "Dukkani Social Login",
    "status": "Authorized",
    "data": json.dumps({
        "email": user,
        "full_name": full_name,
        "provider": "google",
    }),
})
request.insert(ignore_permissions=True, set_name=ticket)
frappe.db.commit()
frappe.response["type"] = "redirect"
frappe.response["location"] = (
    "dukkani-merchant://social/google?ticket=" + ticket
)
'''


EXCHANGE_TICKET_SCRIPT = r'''
ticket = (frappe.form_dict.get("ticket") or "").strip()
if len(ticket) != 64:
    frappe.throw("Invalid social login ticket", frappe.AuthenticationError)

if not frappe.db.exists("Integration Request", ticket):
    frappe.throw("Invalid or expired social login ticket", frappe.AuthenticationError)

request = frappe.get_doc("Integration Request", ticket)
is_social_ticket = (
    request.integration_request_service == "Dukkani Social Login"
    and request.status == "Authorized"
)
is_expired = (
    frappe.utils.time_diff_in_seconds(
        frappe.utils.now_datetime(),
        request.creation,
    ) > 300
)
if not is_social_ticket or is_expired:
    frappe.delete_doc("Integration Request", ticket, ignore_permissions=True)
    frappe.db.commit()
    frappe.throw("Invalid or expired social login ticket", frappe.AuthenticationError)

identity = json.loads(request.data or "{}")
frappe.delete_doc("Integration Request", ticket, ignore_permissions=True)
frappe.db.commit()
frappe.response["message"] = identity
'''


def ensure_api_script(name, method, script, *, allow_guest):
    exists = frappe.db.exists("Server Script", name)
    doc = (
        frappe.get_doc("Server Script", name)
        if exists
        else frappe.new_doc("Server Script")
    )
    if not exists:
        doc.name = name
    doc.script_type = "API"
    doc.api_method = method
    doc.allow_guest = int(allow_guest)
    doc.disabled = 0
    doc.script = script
    if exists:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    print(("Updated" if exists else "Created") + ": " + method)


if frappe.db.exists("Server Script", "Dukkani Google Authorize URL"):
    frappe.delete_doc(
        "Server Script",
        "Dukkani Google Authorize URL",
        ignore_permissions=True,
    )
ensure_api_script(
    "Dukkani Mobile Social Ticket",
    "dukkani_mobile_social_ticket",
    ISSUE_TICKET_SCRIPT,
    allow_guest=False,
)
ensure_api_script(
    "Dukkani Social Ticket Exchange",
    "dukkani_social_ticket_exchange",
    EXCHANGE_TICKET_SCRIPT,
    allow_guest=True,
)

frappe.db.commit()
print("Dukkani social auth bridge is ready.")
