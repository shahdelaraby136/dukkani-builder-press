#!/usr/bin/env python3
# ============================================================
#  Dukkani — مزامنة بيانات التجّار للوحة الأدمن (نسخة Windows/Docker)
#  نفس منطق sync_merchants.sh بس بـ docker exec مباشرة (بلا compose).
#  يقرأ إحصائيات كل متجر ويحدّث سجل "Merchant" في admin.localhost.
#  التشغيل:  python sync_merchants_win.py
# ============================================================
import json
import subprocess

CONTAINER = "dukkani-backend-1"
ADMIN_SITE = "admin.localhost"
SYS_SITES = {"assets", "frontend", ADMIN_SITE}

STATS_PY = r'''
import frappe, json
c = frappe.db.get_single_value("Global Defaults","default_company")
orders = frappe.get_all("Sales Order", fields=["grand_total"])
invoices = frappe.get_all("Sales Invoice", filters={"docstatus":1}, fields=["grand_total"])
owner = frappe.db.get_value("User", {"email":["like","owner@%"], "name":["!=","Administrator"]}, "email") or "-"
print("STATS_JSON:"+json.dumps({
  "merchant_name": c or frappe.local.site, "site_url": frappe.local.site,
  "owner_email": owner,
  "currency": (frappe.db.get_value("Company", c, "default_currency") if c else "SAR"),
  "products": frappe.db.count("Item", {"disabled":0}),
  "customers": frappe.db.count("Customer"),
  "orders": len(orders) + len(invoices),
  "revenue": round(sum((o.grand_total or 0) for o in orders) + sum((i.grand_total or 0) for i in invoices),2),
  "status": "Active",
}, ensure_ascii=False))
'''

UPDATE_PY = r'''
import frappe, json, sys
data = json.loads(open("/tmp/merchants_data.json", encoding="utf-8").read())
for m in data:
    doc = frappe.get_doc("Merchant", m["site_url"]) if frappe.db.exists("Merchant", m["site_url"]) else frappe.new_doc("Merchant")
    doc.update(m)
    doc.last_synced = frappe.utils.now()
    doc.flags.ignore_permissions = True
    doc.save(ignore_permissions=True)
frappe.db.commit()
print("SYNCED", len(data), "merchants")
'''


def _sites():
    r = subprocess.run(["docker", "exec", CONTAINER, "bash", "-lc",
                        "ls -d sites/*/ | sed 's|sites/||;s|/||'"],
                       capture_output=True, text=True)
    return [s for s in r.stdout.split() if s and s not in SYS_SITES]


def _console(site, script_bytes):
    subprocess.run(["docker", "exec", "-i", CONTAINER, "bash", "-c", "cat > /tmp/_s.py"],
                   input=script_bytes)
    r = subprocess.run(["docker", "exec", "-i", CONTAINER, "bench", "--site", site, "console"],
                       input="g={}; exec(open('/tmp/_s.py').read(), g)\n",
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout or ""


def main():
    collected = []
    for s in _sites():
        out = _console(s, STATS_PY.encode("utf-8"))
        for line in out.splitlines():
            if "STATS_JSON:" in line:
                collected.append(json.loads(line.split("STATS_JSON:", 1)[1]))
                print(f"  ✓ {s}")
                break
    # اكتب البيانات جوه الحاوية وحدّث سجل التجّار في الأدمن
    subprocess.run(["docker", "exec", "-i", CONTAINER, "bash", "-c",
                    "cat > /tmp/merchants_data.json"],
                   input=json.dumps(collected, ensure_ascii=False).encode("utf-8"))
    out = _console(ADMIN_SITE, UPDATE_PY.encode("utf-8"))
    for line in out.splitlines():
        if "SYNCED" in line:
            print(line.strip())
    print(f"✅ تم تحديث {len(collected)} تاجر في لوحة الأدمن")


if __name__ == "__main__":
    main()
