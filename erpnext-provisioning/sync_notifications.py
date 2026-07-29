"""Sync Dukkani's ERPNext system notifications across merchant sites.

Run from the provisioning host:
    python erpnext-provisioning/sync_notifications.py
"""

from __future__ import annotations

import json
import subprocess


CONTAINER = "dukkani-backend-1"
BASE_DOMAIN = "dukani.ai"

UPDATE_CODE = r'''
import frappe
import json

def ensure_notification(name, document_type, event, subject, message,
                        value_changed=None, condition=None):
    exists = frappe.db.exists("Notification", name)
    doc = frappe.get_doc("Notification", name) if exists else frappe.new_doc("Notification")
    if not exists:
        doc.name = name
    doc.enabled = 1
    doc.channel = "System Notification"
    doc.document_type = document_type
    doc.event = event
    doc.subject = subject
    doc.message_type = "Markdown"
    doc.message = message
    doc.value_changed = value_changed
    doc.condition = condition
    doc.set("recipients", [])
    for role in ("Website Manager", "Dukkani Team Manager"):
        if frappe.db.exists("Role", role):
            doc.append("recipients", {"receiver_by_role": role})
    doc.save(ignore_permissions=True) if exists else doc.insert(ignore_permissions=True)

ensure_notification(
    "Dukkani Sales Order Status Changed",
    "Sales Order",
    "Value Change",
    "تحديث حالة الطلب #{{ doc.name }}",
    "تم تغيير حالة الطلب **#{{ doc.name }}** إلى **{{ doc.status }}**.",
    value_changed="status",
)
ensure_notification(
    "Dukkani Low Stock Alert",
    "Bin",
    "Value Change",
    "المخزون أوشك على النفاد",
    "متبقي **{{ doc.actual_qty }}** فقط من **{{ doc.item_code }}** في مخزن **{{ doc.warehouse }}**.",
    value_changed="actual_qty",
    condition="doc.actual_qty <= 5",
)
ensure_notification(
    "Dukkani New Store Review",
    "Comment",
    "New",
    "تقييم جديد على {{ doc.reference_name }}",
    "وصل تقييم جديد على **{{ doc.reference_name }}** ويحتاج المراجعة.",
    condition='doc.reference_doctype == "Item" and doc.content and doc.content.startswith("DUKKANI_REVIEW:")',
)
ensure_notification(
    "Dukkani Stock Transfer Submitted",
    "Stock Entry",
    "Submit",
    "تم إتمام تحويل المخزون #{{ doc.name }}",
    "تم اعتماد تحويل المخزون **#{{ doc.name }}** بنجاح.",
    condition='doc.stock_entry_type == "Material Transfer"',
)

frappe.db.commit()
frappe.clear_cache()
print("DUKKANI_NOTIFICATIONS_SYNC:" + json.dumps({
    "site": frappe.local.site,
    "notifications": [
        "Dukkani Sales Order Status Changed",
        "Dukkani Low Stock Alert",
        "Dukkani New Store Review",
        "Dukkani Stock Transfer Submitted",
    ],
}, ensure_ascii=False))
'''


def run(
    command: list[str],
    *,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def marker(output: str, tag: str):
    for line in output.splitlines():
        if tag in line:
            return json.loads(line.split(tag, 1)[1])
    raise RuntimeError(f"Missing marker {tag!r} in output:\n{output}")


def main() -> None:
    run(
        ["docker", "exec", "-i", CONTAINER, "bash", "-lc",
         "cat > /tmp/sync_dukkani_notifications.py"],
        input_text=UPDATE_CODE,
    )
    listed = run(["docker", "exec", "-i", CONTAINER, "bench", "list-sites"])
    sites = sorted(
        {
            line.strip().lstrip("* ").strip()
            for line in listed.stdout.splitlines()
            if line.strip().endswith(f".{BASE_DOMAIN}")
            and line.strip().lstrip("* ").strip()
            not in {BASE_DOMAIN, f"www.{BASE_DOMAIN}"}
        }
    )
    for site in sites:
        result = run(
            ["docker", "exec", "-i", CONTAINER, "bench", "--site", site,
             "console"],
            input_text=(
                'g={}; exec(open("/tmp/sync_dukkani_notifications.py").read(), g)\n'
            ),
        )
        print(marker(result.stdout, "DUKKANI_NOTIFICATIONS_SYNC:"))


if __name__ == "__main__":
    main()
