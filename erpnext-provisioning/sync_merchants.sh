#!/usr/bin/env bash
# ============================================================
#  Dukkani — تحديث بيانات التجار في موقع الأدمن
#  يقرأ إحصائيات كل متجر (منتجات/عملاء/طلبات/مبيعات) من موقعه المعزول
#  ويحدّث سجل "Merchant" في موقع الأدمن admin.localhost.
#  التشغيل:  sg docker -c "bash sync_merchants.sh"
# ============================================================
set -euo pipefail
COMPOSE="docker compose -p frappe_docker"
ADMIN_SITE="admin.localhost"
SYS_SITES="assets frontend ${ADMIN_SITE}"

# سكربت قراءة إحصائيات موقع واحد (يطبع سطر JSON)
read -r -d '' STATS_PY <<'PY' || true
import frappe, json
c = frappe.db.get_single_value("Global Defaults","default_company")
orders = frappe.get_all("Sales Order", fields=["grand_total"])
owner = frappe.db.get_value("User", {"email":["like","owner@%"], "name":["!=","Administrator"]}, "email") or "-"
print("STATS_JSON:"+json.dumps({
  "merchant_name": c or frappe.local.site, "site_url": frappe.local.site,
  "owner_email": owner,
  "currency": (frappe.db.get_value("Company", c, "default_currency") if c else "SAR"),
  "products": frappe.db.count("Item", {"is_stock_item":1,"disabled":0}),
  "customers": frappe.db.count("Customer"),
  "orders": len(orders),
  "revenue": round(sum((o.grand_total or 0) for o in orders),2),
}, ensure_ascii=False))
PY

echo "$STATS_PY" | $COMPOSE exec -T backend bash -c 'cat > /tmp/stats_one.py'

# اكتشاف مواقع التجار
SITES=$($COMPOSE exec -T backend bash -lc 'ls -d sites/*/ | sed "s|sites/||;s|/||"')
COLLECTED="["
first=1
for s in $SITES; do
  skip=0; for sys in $SYS_SITES; do [[ "$s" == "$sys" ]] && skip=1; done
  [[ $skip -eq 1 ]] && continue
  J=$(echo "g={}; exec(open('/tmp/stats_one.py').read(), g)" | $COMPOSE exec -T backend bench --site "$s" console 2>/dev/null | grep -o 'STATS_JSON:.*' | sed 's/STATS_JSON://')
  [[ -z "$J" ]] && continue
  [[ $first -eq 0 ]] && COLLECTED="$COLLECTED,"
  COLLECTED="$COLLECTED$J"; first=0
  echo "  ✓ $s"
done
COLLECTED="$COLLECTED]"

# تحديث سجل التجار في موقع الأدمن
UPDATE_PY="import frappe
data = frappe.parse_json('''$COLLECTED''')
for m in data:
    doc = frappe.get_doc('Merchant', m['site_url']) if frappe.db.exists('Merchant', m['site_url']) else frappe.new_doc('Merchant')
    doc.update(m); doc.status = doc.status or 'Active'; doc.last_synced = frappe.utils.now()
    doc.flags.ignore_permissions = True; doc.save(ignore_permissions=True)
frappe.db.commit()
print('SYNCED', len(data), 'merchants')"
echo "$UPDATE_PY" | $COMPOSE exec -T backend bash -c 'cat > /tmp/update_merchants.py'
echo "g={}; exec(open('/tmp/update_merchants.py').read(), g)" | $COMPOSE exec -T backend bench --site "$ADMIN_SITE" console 2>&1 | grep -E "SYNCED|Error" | head -2
echo "✅ تم تحديث بيانات التجار في موقع الأدمن"
