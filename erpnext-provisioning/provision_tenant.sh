#!/usr/bin/env bash
# ============================================================
#  Dukkani — تجهيز تاجر جديد آلياً (Provisioning)
#  ينفّذ فلو التجهيز بالترتيب الصحيح:
#    3) إنشاء Site + قاعدة بيانات معزولة + ERPNext
#    4) تطبيق قالب دكاني (tenant_template.py) بداخله
#    5) ضبط الدومين الفرعي محلياً
#
#  الاستخدام:
#    sudo bash provision_tenant.sh <subdomain> "<Merchant Name>"
#  مثال:
#    sudo bash provision_tenant.sh nourstore "Nour Fashion Store"
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_DIR="/home/shahd/frappe_docker"
COMPOSE="docker compose -f pwd.yml"
DB_ROOT_PASS="${DUKKANI_DB_ROOT_PASSWORD:?DUKKANI_DB_ROOT_PASSWORD is required}"
ADMIN_PASS="${DUKKANI_SITE_ADMIN_PASSWORD:?DUKKANI_SITE_ADMIN_PASSWORD is required}"

SUBDOMAIN="${1:-merchant1}"
MERCHANT_NAME="${2:-Dukkani Merchant}"
MERCHANT_EMAIL="${3:-owner@${SUBDOMAIN}.dukkani.ai}"   # إيميل مالك المتجر (من فورم التسجيل)
MERCHANT_PASSWORD="${4:-}"                               # باسورد التاجر (من فورم التسجيل)
MERCHANT_COUNTRY="${5:-Saudi Arabia}"                   # دولة التاجر (من كود الدولة في التسجيل)
SITE="${SUBDOMAIN}.localhost"          # محلياً؛ في الإنتاج: ${SUBDOMAIN}.dukkani.ai
ABBR="$(echo "$MERCHANT_NAME" | awk '{for(i=1;i<=NF && i<=3;i++) printf toupper(substr($i,1,1))}')"
[[ -z "$ABBR" ]] && ABBR="DKN"

log()  { echo -e "\n\033[1;36m==> $*\033[0m"; }
ok()   { echo -e "\033[1;32m✓ $*\033[0m"; }
warn() { echo -e "\033[1;33m[!] $*\033[0m"; }

# يحتاج صلاحية تشغيل Docker (root أو عضوية مجموعة docker) — لا يشترط root.
docker info >/dev/null 2>&1 || { echo "لا صلاحية لتشغيل Docker (شغّل بـ sudo أو أضف المستخدم لمجموعة docker)"; exit 1; }
cd "$BENCH_DIR"
$COMPOSE ps --status running | grep -q backend || { warn "ERPNext مش شغّال — cd ~/frappe_docker && $COMPOSE up -d"; exit 1; }

echo "============================================================"
echo "  تجهيز تاجر جديد"
echo "  الاسم     : $MERCHANT_NAME"
echo "  الاختصار  : $ABBR"
echo "  الدومين   : $SITE"
echo "============================================================"

# ---- (3) إنشاء الـ Site أولاً ----
# فحص موثوق: وجود ملف إعداد الموقع (bench version لا يتحقق من صحة الموقع).
if $COMPOSE exec -T backend test -f "sites/$SITE/site_config.json" 2>/dev/null; then
  warn "الموقع $SITE موجود بالفعل — نكمّل لتطبيق القالب."
else
  log "3) إنشاء الـ Site + قاعدة بيانات معزولة + ERPNext ..."
  $COMPOSE exec -T backend bench new-site "$SITE" \
    --mariadb-user-host-login-scope='%' \
    --admin-password="$ADMIN_PASS" \
    --db-root-username=root \
    --db-root-password="$DB_ROOT_PASS" \
    --install-app erpnext
  ok "اتعمل الموقع + قاعدة بياناته الخاصة."
fi

# ---- (4) تطبيق القالب بداخله ----
# نسخ القالب داخل الكونتينر ثم تشغيله كسكريبت بايثون واحد (namespace واحد)
# ملاحظة: exec للملف كله دفعة واحدة يتفادى تقسيم IPython للأكواد.
log "4) تطبيق قالب دكاني على $SITE ..."
$COMPOSE cp "$SCRIPT_DIR/tenant_template.py" backend:/tmp/tenant_template.py
echo "g={}; exec(open('/tmp/tenant_template.py').read(), g)" | $COMPOSE exec -T \
  -e MERCHANT_NAME="$MERCHANT_NAME" \
  -e MERCHANT_ABBR="$ABBR" \
  -e MERCHANT_EMAIL="$MERCHANT_EMAIL" \
  -e MERCHANT_PASSWORD="$MERCHANT_PASSWORD" \
  -e MERCHANT_COUNTRY="$MERCHANT_COUNTRY" \
  backend bench --site "$SITE" console

# Builder storefront: install the visual editor and seed editable starter themes.
$COMPOSE exec -T backend bench --site "$SITE" install-app builder || true
$COMPOSE exec -T backend bench --site "$SITE" migrate
$COMPOSE cp "$SCRIPT_DIR/storefront_starter.py" backend:/tmp/storefront_starter.py
$COMPOSE cp "$SCRIPT_DIR/storefront_cart.js" backend:/tmp/storefront_cart.js
echo "g={}; exec(open('/tmp/storefront_starter.py').read(), g)" | $COMPOSE exec -T \
  -e MERCHANT_EMAIL="$MERCHANT_EMAIL" backend bench --site "$SITE" console
ok "اتطبّق القالب (شركة + دليل حسابات + ضريبة 15% + أدوار + وسائل دفع + يوزر المالك)."

# مسح الكاش ليأخذ الإعداد (وتخطّي معالج الإعداد) مفعوله فوراً
$COMPOSE exec -T backend bench --site "$SITE" clear-cache >/dev/null 2>&1 || true
$COMPOSE exec -T backend bench --site "$SITE" clear-website-cache >/dev/null 2>&1 || true

# ---- (5) الدومين الفرعي محلياً ----
# ‏*.localhost يترجم تلقائياً لـ 127.0.0.1؛ نكتب في /etc/hosts فقط لو كنا root.
if [[ "$(id -u)" -eq 0 ]] && ! grep -q "$SITE" /etc/hosts; then
  echo "127.0.0.1 $SITE" >> /etc/hosts
  ok "5) اتربط الدومين $SITE بـ 127.0.0.1"
fi

cat <<EOF

============================================================
  ✅ التاجر جاهز
============================================================
  الرابط         : http://$SITE:8080
  ── دخول التاجر (الشكل النضيف) ──
  المالك         : $MERCHANT_EMAIL
  الباسورد       : <hidden>
  ── حساب BDC الداخلي للدعم ──
  Administrator  : <hidden>
  الشركة         : $MERCHANT_NAME  ($ABBR)
============================================================
EOF
