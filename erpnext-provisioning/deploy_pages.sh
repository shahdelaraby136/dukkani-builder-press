#!/usr/bin/env bash
# ============================================================
#  Dukkani — إعادة نشر صفحات الويب (signup / platform / shop)
#  داخل حاوية ERPNext. يُشغَّل مع كل بداية عشان الصفحات ما تضيعش
#  لو الحاوية اتعملها recreate. آمن للتكرار.
# ============================================================
export MSYS_NO_PATHCONV=1
set -uo pipefail
C=dukkani-backend-1
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/api"
WWW=/home/frappe/frappe-bench/apps/frappe/frappe/www

docker exec "$C" true 2>/dev/null || { echo "الحاوية مش شغّالة"; exit 1; }

# /shop is now provided by each tenant's selected Builder storefront.
for f in signup platform; do
  if [ -f "$DIR/$f.html" ]; then
    docker exec -i "$C" bash -c "cat > $WWW/$f.html" < "$DIR/$f.html" && echo "  ✓ نُشرت $f.html"
  fi
done

# مسح كاش الويب لكل المواقع عشان تظهر فورًا
SITES=$(docker exec "$C" bash -lc 'ls -d sites/*.localhost/ 2>/dev/null | sed "s|sites/||;s|/||"')
for s in $SITES; do
  docker exec "$C" bench --site "$s" clear-website-cache >/dev/null 2>&1
done
echo "✅ اتنشرت الصفحات + اتمسح الكاش"
