# ============================================================
#  Dukkani — إنشاء doctypes لوحة الأدمن (admin.localhost)
#  Merchant + Merchant Registration — حقول مستخرجة من
#  sync_merchants.sh و provision_watcher.sh (بلا اختراع).
#  آمن للتكرار (idempotent).
# ============================================================
import frappe


def _make(name, autoname, fields, title_field=None, in_list=None):
    if frappe.db.exists("DocType", name):
        print(f"موجود بالفعل: {name}")
        return
    doc = frappe.get_doc({
        "doctype": "DocType",
        "name": name,
        "module": "Custom",
        "custom": 1,
        "autoname": autoname,
        "title_field": title_field,
        "track_changes": 1,
        "fields": fields,
        "permissions": [{
            "role": "System Manager",
            "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1,
        }],
    })
    doc.insert(ignore_permissions=True)
    print(f"تم إنشاء: {name}")


# ---- Merchant (قائمة التجّار — هي اللي في الصورة) ----
_make(
    "Merchant",
    autoname="field:site_url",
    title_field="merchant_name",
    fields=[
        {"fieldname": "merchant_name", "label": "التاجر", "fieldtype": "Data", "in_list_view": 1, "reqd": 1},
        {"fieldname": "status", "label": "الحالة", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "products", "label": "المنتجات", "fieldtype": "Int", "in_list_view": 1},
        {"fieldname": "customers", "label": "العملاء", "fieldtype": "Int", "in_list_view": 1},
        {"fieldname": "orders", "label": "الطلبات", "fieldtype": "Int", "in_list_view": 1},
        {"fieldname": "revenue", "label": "المبيعات", "fieldtype": "Currency", "in_list_view": 1},
        {"fieldname": "cb1", "fieldtype": "Column Break"},
        {"fieldname": "site_url", "label": "المتجر", "fieldtype": "Data", "in_list_view": 1, "reqd": 1, "unique": 1},
        {"fieldname": "owner_email", "label": "المالك", "fieldtype": "Data"},
        {"fieldname": "currency", "label": "العملة", "fieldtype": "Data"},
        {"fieldname": "last_synced", "label": "آخر تحديث", "fieldtype": "Datetime", "read_only": 1},
    ],
)

# ---- Merchant Registration (طلبات التسجيل — للـ watcher) ----
_make(
    "Merchant Registration",
    autoname="field:subdomain",
    title_field="merchant_name",
    fields=[
        {"fieldname": "merchant_name", "label": "اسم المتجر", "fieldtype": "Data", "in_list_view": 1, "reqd": 1},
        {"fieldname": "subdomain", "label": "النطاق الفرعي", "fieldtype": "Data", "in_list_view": 1, "reqd": 1, "unique": 1},
        {"fieldname": "email", "label": "البريد", "fieldtype": "Data", "in_list_view": 1},
        {"fieldname": "country", "label": "الدولة", "fieldtype": "Data", "default": "Saudi Arabia"},
        {"fieldname": "password", "label": "كلمة المرور", "fieldtype": "Password"},
        {"fieldname": "cb1", "fieldtype": "Column Break"},
        {"fieldname": "status", "label": "الحالة", "fieldtype": "Select",
         "options": "Pending\nProvisioning\nDone\nFailed", "default": "Pending", "in_list_view": 1},
        {"fieldname": "site_url", "label": "رابط المتجر", "fieldtype": "Data", "read_only": 1},
        {"fieldname": "message", "label": "رسالة", "fieldtype": "Small Text", "read_only": 1},
    ],
)

frappe.db.commit()
print("===== ✅ اتعملت doctypes لوحة الأدمن =====")
