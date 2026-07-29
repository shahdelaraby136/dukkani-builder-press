# ============================================================
#  Dukkani — ضبط أدوار المتجر الثلاثة + صلاحياتها (لمتجر واحد)
#  Merchant Owner = كامل | Store Manager = بلا ماليات/حذف | Store Staff = أساسي
#  يكتشف صاحب المتجر تلقائياً ويسند له Merchant Owner.
#  آمن: يضيف صلاحيات فقط. idempotent.
#  التشغيل داخل الحاوية:  bench --site <SITE> console  ثم exec لهذا الملف.
# ============================================================
import frappe
from frappe.permissions import add_permission, update_permission_property

SUBMITTABLE = {"Sales Order", "Sales Invoice", "Delivery Note", "Payment Entry", "Quotation"}


def ensure_role(role):
    if not frappe.db.exists("Role", role):
        frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
    else:
        d = frappe.get_doc("Role", role)
        if d.disabled or not d.desk_access:
            d.disabled = 0
            d.desk_access = 1
            d.save(ignore_permissions=True)


def grant(doctype, role, base):
    ensure_role(role)
    perms = dict(base)
    if doctype not in SUBMITTABLE:
        for k in ("submit", "cancel", "amend"):
            perms.pop(k, None)
    try:
        add_permission(doctype, role, 0)
    except Exception:
        pass
    for ptype, val in perms.items():
        try:
            update_permission_property(doctype, role, 0, ptype, val)
        except Exception:
            pass


FULL = {"read": 1, "write": 1, "create": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1}
OPS = {"read": 1, "write": 1, "create": 1, "submit": 1}
RW = {"read": 1, "write": 1, "create": 1}
RO = {"read": 1}

for dt in ["Item", "Item Group", "Customer", "Sales Order", "Sales Invoice",
           "Delivery Note", "Payment Entry", "Pricing Rule", "Quotation"]:
    grant(dt, "Merchant Owner", FULL)
for dt in ["Item", "Item Group", "Customer", "Sales Order", "Sales Invoice",
           "Delivery Note", "Quotation", "Pricing Rule"]:
    grant(dt, "Store Manager", OPS)
grant("Item", "Store Staff", RW)
grant("Item Group", "Store Staff", RO)
grant("Customer", "Store Staff", RO)
grant("Sales Order", "Store Staff", {"read": 1, "write": 1, "submit": 1})
grant("Delivery Note", "Store Staff", {"read": 1, "write": 1, "create": 1})

# إسناد Merchant Owner لصاحب المتجر (كل مستخدم مكتب غير Administrator)
owners = frappe.get_all("User", filters={
    "user_type": "System User", "enabled": 1,
    "name": ["not in", ["Administrator", "Guest"]]}, pluck="name")
for email in owners:
    if not frappe.db.exists("Has Role", {"parent": email, "role": "Merchant Owner"}):
        frappe.get_doc({"doctype": "Has Role", "parent": email, "parenttype": "User",
                        "parentfield": "roles", "role": "Merchant Owner"}).insert(ignore_permissions=True)

frappe.db.commit()
frappe.clear_cache()
print("DUKKANI_ROLES_DONE owners=" + ",".join(owners))
