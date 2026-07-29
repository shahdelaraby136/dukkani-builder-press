#!/usr/bin/env bash
# ============================================================
#  تشغيل Dukkani Provisioning API
#  ملاحظة: يجب أن يعمل بصلاحية تشغيل Docker (root أو مجموعة docker)
#  لأنه ينفّذ أوامر bench داخل الكونتينر.
#
#  الاستخدام:  sudo bash run.sh
# ============================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV=".venv"
if [[ ! -d "$VENV" ]]; then
  echo "==> إنشاء بيئة بايثون وتثبيت المتطلبات..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r requirements.txt
fi

echo "==> تشغيل الـ API على http://0.0.0.0:9000  (التوثيق: /docs)"
exec "$VENV/bin/uvicorn" main:app --host 0.0.0.0 --port 9000
