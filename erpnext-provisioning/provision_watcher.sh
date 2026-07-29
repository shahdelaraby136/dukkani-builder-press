#!/usr/bin/env bash
# ============================================================
#  Dukkani — محرّك التجهيز (Provisioning Watcher)
#  يراقب طلبات التسجيل (Merchant Registration) في موقع الأدمن،
#  وينشئ متجرًا تلقائيًا لكل طلب جديد، ثم يسجّله في قائمة التجّار.
#  التشغيل (في الخلفية):  sg docker -c "bash provision_watcher.sh"
# ============================================================
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE="docker compose -p frappe_docker"
ADMIN="admin.localhost"
TMP=/tmp/dkn_pending.txt

log(){ echo -e "\033[1;36m[watcher]\033[0m $*"; }

# سكربت جلب الطلبات المعلّقة (يطبع سطر JSON لكل طلب مع كلمة المرور)
read -r -d '' GET_PY <<'PY' || true
import frappe, json
for r in frappe.get_all("Merchant Registration", filters={"status":"Pending"},
                        fields=["name","merchant_name","subdomain","email","country"]):
    r["password"] = frappe.get_doc("Merchant Registration", r["name"]).get_password("password") or ""
    print("REG_JSON:"+json.dumps(r, ensure_ascii=False))
PY
echo "$GET_PY" | $COMPOSE exec -T backend bash -c 'cat > /tmp/get_pending.py'

set_status(){  # $1=subdomain  $2=status  $3=site_url  $4=message
  local py="import frappe
d=frappe.get_doc('Merchant Registration','$1')
d.status='$2'
d.site_url='${3:-}'
d.message='''${4:-}'''
d.flags.ignore_permissions=True; d.save(ignore_permissions=True)
frappe.db.commit()
print('OK')"
  echo "$py" | $COMPOSE exec -T backend bash -c 'cat > /tmp/set_reg.py'
  echo "g={}; exec(open('/tmp/set_reg.py').read(), g)" | $COMPOSE exec -T backend bench --site "$ADMIN" console >/dev/null 2>&1 || true
}

process_once(){
  echo "g={}; exec(open('/tmp/get_pending.py').read(), g)" | $COMPOSE exec -T backend bench --site "$ADMIN" console 2>/dev/null \
    | grep -o 'REG_JSON:.*' | sed 's/REG_JSON://' > "$TMP" || true
  [ -s "$TMP" ] || return 0
  local did=0
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    SUB=$(echo "$line" | python3 -c "import sys,json;print(json.load(sys.stdin)['subdomain'])")
    MNAME=$(echo "$line" | python3 -c "import sys,json;print(json.load(sys.stdin)['merchant_name'])")
    EMAIL=$(echo "$line" | python3 -c "import sys,json;print(json.load(sys.stdin)['email'])")
    PW=$(echo "$line" | python3 -c "import sys,json;print(json.load(sys.stdin)['password'])")
    COUNTRY=$(echo "$line" | python3 -c "import sys,json;print(json.load(sys.stdin).get('country') or 'Saudi Arabia')")
    log "طلب جديد: $MNAME ($SUB) — بدء التجهيز"
    set_status "$SUB" "Provisioning" "" ""
    if bash "$DIR/provision_tenant.sh" "$SUB" "$MNAME" "$EMAIL" "$PW" "$COUNTRY" >/tmp/prov_"$SUB".log 2>&1; then
      set_status "$SUB" "Done" "$SUB.localhost" "تم التجهيز بنجاح"
      log "✅ اتجهّز متجر $SUB — http://$SUB.localhost:8080"
      did=1
    else
      set_status "$SUB" "Failed" "" "$(tail -3 /tmp/prov_$SUB.log 2>/dev/null | tr '\n' ' ')"
      log "❌ فشل تجهيز $SUB (شوف /tmp/prov_$SUB.log)"
    fi
  done < "$TMP"
  # حدّث قائمة التجّار في الأدمن لو اتعمل تجهيز
  [ "$did" = "1" ] && bash "$DIR/sync_merchants.sh" >/dev/null 2>&1 && log "🔄 اتحدّثت قائمة التجّار في الأدمن"
  return 0
}

log "المحرّك اشتغل — بيراقب طلبات التسجيل كل 8 ثواني…"
while true; do
  process_once
  sleep 8
done
