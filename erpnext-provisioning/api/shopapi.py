# ============================================================
#  Dukkani — واجهة المتجر (Storefront API)
#  عرض منتجات المتجر + إتمام طلب الزبون — بلا تركيب أي تطبيق.
#  يعمل عبر خدمة التجهيز (المنفذ 9000) ويكلّم موقع المتجر بـ docker exec.
#  آمن تماماً: لا يعدّل أي شيء في الإعداد القائم.
# ============================================================
import json
import os
import subprocess
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CONTAINER = "dukkani-backend-1"
PORT = 8090
BASE_DOMAIN = os.environ.get("DUKKANI_BASE_DOMAIN", "localhost").strip().lower()
_RUN_LOCK = threading.Lock()


def _site_name(sub):
    """Map a public store slug to its actual isolated Frappe site."""
    return f"{sub}.{BASE_DOMAIN}"


def reverse_geocode(lat, lng):
    """Resolve browser coordinates to an Arabic delivery address."""
    query = urlencode({"format": "jsonv2", "lat": lat, "lon": lng,
                       "addressdetails": 1, "accept-language": "ar"})
    request = Request(
        "https://nominatim.openstreetmap.org/reverse?" + query,
        headers={"User-Agent": "Dukkani-Storefront/1.0 (local-development)"},
    )
    with urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    address = result.get("address") or {}
    return {
        "city": address.get("city") or address.get("town") or address.get("village")
                or address.get("municipality") or address.get("state") or "",
        "district": address.get("suburb") or address.get("neighbourhood")
                    or address.get("city_district") or address.get("quarter") or "",
        "address": result.get("display_name") or "",
        "lat": str(result.get("lat") or lat),
        "lng": str(result.get("lon") or lng),
    }


def _run(site, code, infile=None, indata=None):
    """يشغّل كود بايثون داخل موقع المتجر ويرجّع stdout."""
    # All requests used the same temporary files. Parallel product/order calls
    # could overwrite each other's code or payload and return an empty result.
    with _RUN_LOCK:
        subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "bash", "-c", "cat > /tmp/_shop.py"],
            input=code.encode("utf-8"), check=True, timeout=30,
        )
        if infile and indata is not None:
            subprocess.run(
                ["docker", "exec", "-i", CONTAINER, "bash", "-c", f"cat > {infile}"],
                input=json.dumps(indata, ensure_ascii=False).encode("utf-8"),
                check=True, timeout=30,
            )
        result = subprocess.run(
            ["docker", "exec", "-i", CONTAINER, "bench", "--site", site, "console"],
            input="g={}; exec(open('/tmp/_shop.py').read(), g)\n",
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"storefront command failed ({result.returncode})")
        return result.stdout or ""


def _marker(out, tag):
    for line in out.splitlines():
        if tag in line:
            return json.loads(line.split(tag, 1)[1])
    return None


LIST_CODE = r'''
import frappe, json
pl = frappe.db.get_value("Price List", {"selling":1}, "name")
company = frappe.db.get_single_value("Global Defaults","default_company")
cur = frappe.db.get_value("Company", company, "default_currency") if company else "SAR"

def _review_rows(item_code):
    rows = []
    for row in frappe.get_all(
        "Comment",
        filters={"reference_doctype": "Item", "reference_name": item_code, "comment_type": "Comment"},
        fields=["content", "comment_by", "comment_email", "creation"],
        order_by="creation desc",
        limit_page_length=100,
    ):
        content = (row.content or "").strip()
        if not content.startswith("DUKKANI_REVIEW:"):
            continue
        try:
            payload = json.loads(content.split("DUKKANI_REVIEW:", 1)[1])
        except Exception:
            continue
        rating = int(payload.get("rating") or 0)
        if rating < 1 or rating > 5 or payload.get("approved") is not True:
            continue
        rows.append({
            "name": payload.get("name") or row.comment_by or "عميل",
            "rating": rating,
            "comment": payload.get("comment") or "",
            "created_at": str(row.creation),
        })
    return rows

out = []
for it in frappe.get_all("Item", filters={"disabled":0}, fields=["name","item_name","image","description"]):
    rate = frappe.db.get_value("Item Price", {"item_code":it["name"],"selling":1}, "price_list_rate") or 0
    stock_qty = frappe.db.sql("""
        SELECT COALESCE(SUM(actual_qty), 0)
        FROM `tabBin`
        WHERE item_code = %s
    """, it["name"])[0][0] or 0
    reviews = _review_rows(it["name"])
    rating_count = len(reviews)
    rating_avg = round(sum(row["rating"] for row in reviews) / rating_count, 1) if rating_count else 0
    out.append({"code":it["name"], "name":it["item_name"], "rate":rate,
                "image":it.get("image") or "", "desc":(it.get("description") or ""),
                "stock_qty": float(stock_qty), "out_of_stock": float(stock_qty) <= 0,
                "rating_avg": rating_avg, "rating_count": rating_count,
                "reviews": reviews[:8]})
print("SHOP_JSON:"+json.dumps({"currency":cur, "store":company, "items":out}, ensure_ascii=False))
'''

REVIEW_CODE = r'''
import frappe, json
d = json.load(open("/tmp/review_in.json", encoding="utf-8"))
code = (d.get("code") or "").strip()
name = (d.get("name") or "عميل").strip()[:80]
email = (d.get("email") or "").strip().lower()[:140]
comment = (d.get("comment") or "").strip()[:800]
try:
    rating = int(d.get("rating") or 0)
except Exception:
    rating = 0
if not code or not frappe.db.exists("Item", code):
    frappe.throw("المنتج غير موجود")
if rating < 1 or rating > 5:
    frappe.throw("اختاري تقييم من 1 إلى 5")
if len(comment) < 2:
    frappe.throw("اكتبي تعليق قصير")
payload = {"name": name or "عميل", "email": email, "rating": rating,
           "comment": comment, "approved": False, "reply": ""}
doc = frappe.get_doc({
    "doctype": "Comment", "comment_type": "Comment",
    "reference_doctype": "Item", "reference_name": code,
    "comment_by": payload["name"], "comment_email": email,
    "content": "DUKKANI_REVIEW:" + json.dumps(payload, ensure_ascii=False),
})
doc.insert(ignore_permissions=True)
frappe.db.commit()
print("REVIEW_JSON:"+json.dumps({"ok": True, "review": {
    "name": payload["name"], "rating": rating, "comment": comment,
    "created_at": str(doc.creation),
}}, ensure_ascii=False))
'''

ORDER_CODE = r'''
import frappe, json
d = json.load(open("/tmp/order_in.json", encoding="utf-8"))
cname = (d.get("customer_name") or "زبون").strip()
phone = (d.get("phone") or "").strip()
email = (d.get("email") or "").strip().lower()
cust = frappe.db.get_value("Customer", {"customer_name":cname})
if not cust:
    cg = frappe.db.get_value("Customer Group", {"is_group":0}, "name") or "All Customer Groups"
    terr = frappe.db.get_value("Territory", {"is_group":0}, "name") or "All Territories"
    c = frappe.get_doc({"doctype":"Customer","customer_name":cname,"customer_type":"Individual",
                        "customer_group":cg,"territory":terr,"mobile_no":phone,"email_id":email})
    c.insert(ignore_permissions=True); cust = c.name
elif email:
    frappe.db.set_value("Customer", cust, {"email_id": email, "mobile_no": phone})
company = frappe.db.get_single_value("Global Defaults","default_company")
wh = frappe.db.get_value("Warehouse", {"company":company,"is_group":0}, "name")
company_currency = frappe.db.get_value("Company", company, "default_currency") if company else None
company_currency = company_currency or frappe.db.get_default("currency") or "EGP"
price_list = (
    frappe.db.get_value("Price List", {"selling": 1, "currency": company_currency}, "name")
    or frappe.db.get_value("Price List", {"selling": 1}, "name")
    or "Standard Selling"
)
if frappe.db.exists("Price List", price_list):
    frappe.db.set_value("Price List", price_list, "currency", company_currency)
items = []
for i in d["items"]:
    code = i["code"]
    qty = frappe.utils.flt(i.get("qty") or 1)
    stock_qty = frappe.db.sql("""
        SELECT COALESCE(SUM(actual_qty), 0)
        FROM `tabBin`
        WHERE item_code = %s
    """, code)[0][0] or 0
    if float(stock_qty) < qty:
        frappe.throw("المنتج غير متوفر حالياً: " + code)
    items.append({"item_code": code, "qty": qty,
                  "rate": frappe.utils.flt(i.get("rate") or 0), "warehouse": wh})
so = frappe.get_doc({"doctype":"Sales Order","customer":cust,"company":company,
    "currency": company_currency, "conversion_rate": 1,
    "selling_price_list": price_list, "price_list_currency": company_currency,
    "plc_conversion_rate": 1,
    "delivery_date": frappe.utils.add_days(frappe.utils.nowdate(),3), "items":items})
so.insert(ignore_permissions=True)
so.submit()
# تفاصيل التوصيل كتعليق على الطلب (يشوفها التاجر)
det = []
if phone: det.append("الجوال: " + phone)
for lbl, key in [("المدينة","city"),("الحي","district"),("العنوان","address"),("طريقة الدفع","payment")]:
    if d.get(key): det.append(lbl + ": " + str(d[key]))
if d.get("lat") and d.get("lng"):
    det.append("الموقع على الخريطة: https://maps.google.com/?q=" + str(d["lat"]) + "," + str(d["lng"]))
if det:
    so.add_comment("Comment", "🚚 بيانات التوصيل\n" + "\n".join(det))
merchant_users = frappe.get_all(
    "Has Role",
    filters={
        "role": ["in", ["Merchant Owner", "Website Manager"]],
        "parenttype": "User",
        "parent": ["not in", ["Administrator", "Guest"]],
    },
    pluck="parent",
)
merchant_users = list(dict.fromkeys(
    user for user in merchant_users
    if frappe.db.get_value("User", user, "enabled")
))

# Keep the in-app bell independent from outgoing email configuration.
for merchant in merchant_users:
    frappe.get_doc({
        "doctype": "Notification Log",
        "subject": f"\u0637\u0644\u0628 \u062c\u062f\u064a\u062f #{so.name}",
        "email_content": (
            f"<div dir='rtl'>\u062a\u0645 \u0627\u0633\u062a\u0644\u0627\u0645 \u0637\u0644\u0628 \u062c\u062f\u064a\u062f "
            f"\u0628\u0642\u064a\u0645\u0629 {so.grand_total:,.2f} {so.currency}</div>"
        ),
        "for_user": merchant,
        "type": "Alert",
        "document_type": "Sales Order",
        "document_name": so.name,
        "from_user": "Administrator",
        "link": f"/app/sales-order/{so.name}",
    }).insert(ignore_permissions=True)

notification = "not_configured"
if frappe.db.exists("Email Account", {"enable_outgoing": 1}):
    rows = "".join(
        f"<li>{frappe.utils.escape_html(i.item_name)} × {i.qty} — {i.amount:,.2f}</li>"
        for i in so.items
    )
    details = f"<p>رقم الطلب: <b>{so.name}</b></p><ul>{rows}</ul><p>الإجمالي: <b>{so.grand_total:,.2f} {so.currency}</b></p>"
    if email:
        frappe.sendmail(recipients=[email], subject=f"تأكيد طلبك {so.name}",
            message=f"<div dir='rtl'><h2>تم استلام طلبك بنجاح</h2>{details}<p>سنتواصل معك لتأكيد التوصيل.</p></div>",
            reference_doctype="Sales Order", reference_name=so.name, now=True)
    for merchant in merchant_users:
        frappe.sendmail(recipients=[merchant], subject=f"طلب جديد {so.name}",
            message=f"<div dir='rtl'><h2>وصل طلب جديد من {frappe.utils.escape_html(cname)}</h2>{details}<p>الجوال: {frappe.utils.escape_html(phone)}</p></div>",
            reference_doctype="Sales Order", reference_name=so.name, now=True)
    notification = "sent"
frappe.db.commit()
print("ORDER_JSON:"+json.dumps({"order":so.name, "total":so.grand_total,
      "currency":frappe.db.get_value("Company", company, "default_currency"),
      "email_notification": notification}, ensure_ascii=False))
'''


TRACK_ORDER_CODE = r'''
import frappe, json
d = json.load(open("/tmp/track_order_in.json", encoding="utf-8"))
order_name = (d.get("order") or "").strip()
email = (d.get("email") or "").strip().lower()
result = None
if order_name and email and frappe.db.exists("Sales Order", order_name):
    order = frappe.get_doc("Sales Order", order_name)
    customer_email = (frappe.db.get_value("Customer", order.customer, "email_id") or "").strip().lower()
    if customer_email and customer_email == email:
        labels = {"Draft":"تم استلام الطلب","On Hold":"الطلب معلّق","To Deliver and Bill":"تم تأكيد الطلب وجاري التجهيز","To Deliver":"خرج للتوصيل","To Bill":"تم التسليم","Completed":"تم التسليم","Cancelled":"تم إلغاء الطلب","Closed":"تم إغلاق الطلب"}
        steps = {"Draft":1,"On Hold":1,"To Deliver and Bill":2,"To Deliver":3,"To Bill":4,"Completed":4,"Cancelled":0,"Closed":0}
        result = {"order":order.name,"status":order.status,"status_label":labels.get(order.status,order.status),"step":steps.get(order.status,1),"customer":order.customer_name,"total":order.grand_total,"currency":order.currency,"date":str(order.transaction_date),"cancelled":order.status in ("Cancelled","Closed")}
print("TRACK_JSON:" + json.dumps({"found":bool(result),"data":result}, ensure_ascii=False))
'''


def list_products(sub):
    out = _run(_site_name(sub), LIST_CODE)
    data = _marker(out, "SHOP_JSON:")
    return data or {"currency": "SAR", "store": sub, "items": []}


def place_order(sub, payload):
    out = _run(_site_name(sub), ORDER_CODE, infile="/tmp/order_in.json", indata=payload)
    data = _marker(out, "ORDER_JSON:")
    if not data:
        raise RuntimeError("order failed: " + out[-400:])
    return data


def track_order(sub, order, email):
    out = _run(_site_name(sub), TRACK_ORDER_CODE, infile="/tmp/track_order_in.json",
               indata={"order": order, "email": email})
    data = _marker(out, "TRACK_JSON:")
    if data is None:
        raise RuntimeError("order tracking failed: " + out[-400:])
    return data


CUSTOMER_ORDERS_CODE = r'''
import frappe, json
d = json.load(open("/tmp/customer_orders_in.json", encoding="utf-8"))
email = (d.get("email") or "").strip().lower()
labels = {"Draft":"تم استلام الطلب","On Hold":"الطلب معلّق","To Deliver and Bill":"تم تأكيد الطلب وجاري التجهيز","To Deliver":"خرج للتوصيل","To Bill":"تم التسليم","Completed":"تم التسليم","Cancelled":"تم إلغاء الطلب","Closed":"تم إغلاق الطلب"}
orders = []
if email:
    rows = frappe.db.sql("""
        select so.name, so.status, so.transaction_date, so.grand_total, so.currency,
               so.customer_name
        from `tabSales Order` so
        inner join `tabCustomer` c on c.name = so.customer
        where lower(coalesce(c.email_id, '')) = %s
        order by so.creation desc
        limit 50
    """, email, as_dict=True)
    orders = [{
        "order": row.name, "status": row.status,
        "status_label": labels.get(row.status, row.status),
        "date": str(row.transaction_date), "total": row.grand_total,
        "currency": row.currency, "customer": row.customer_name,
    } for row in rows]
print("CUSTOMER_ORDERS_JSON:" + json.dumps({"orders": orders}, ensure_ascii=False, default=str))
'''


def customer_orders(sub, email):
    out = _run(_site_name(sub), CUSTOMER_ORDERS_CODE,
               infile="/tmp/customer_orders_in.json", indata={"email": email})
    data = _marker(out, "CUSTOMER_ORDERS_JSON:")
    if data is None:
        raise RuntimeError("تعذّر تحميل طلبات العميل.")
    return data


def add_review(sub, payload):
    out = _run(_site_name(sub), REVIEW_CODE, infile="/tmp/review_in.json", indata=payload)
    data = _marker(out, "REVIEW_JSON:")
    if not data:
        raise RuntimeError("review failed: " + out[-400:])
    return data


CUSTOMER_REGISTER_CODE = r'''
import frappe, json, re
d = json.load(open("/tmp/customer_register_in.json", encoding="utf-8"))
first_name = (d.get("first_name") or "").strip()
last_name = (d.get("last_name") or "").strip()
email = (d.get("email") or "").strip().lower()
phone = re.sub(r"[^0-9+]", "", (d.get("phone") or "").strip())
password = d.get("password") or ""
result = {"created": False, "detail": "تعذّر إنشاء الحساب."}
if len(first_name) < 2 or len(last_name) < 2:
    result["detail"] = "اكتب الاسم الأول واسم العائلة بشكل صحيح."
elif not frappe.utils.validate_email_address(email):
    result["detail"] = "البريد الإلكتروني غير صالح."
elif len(phone) < 7:
    result["detail"] = "رقم الجوال غير صالح."
elif len(password) < 8:
    result["detail"] = "كلمة المرور يجب أن تكون 8 أحرف على الأقل."
elif frappe.db.exists("User", email):
    result["detail"] = "هذا البريد مسجل بالفعل؛ يمكنك تسجيل الدخول مباشرة."
elif frappe.db.exists("User", {"mobile_no": phone}):
    result["detail"] = "رقم الهاتف مرتبط بحساب آخر."
else:
    try:
        user = frappe.get_doc({
            "doctype": "User", "email": email, "first_name": first_name,
            "last_name": last_name, "mobile_no": phone, "enabled": 1,
            "user_type": "Website User", "new_password": password,
            "send_welcome_email": 0,
        })
        user.flags.ignore_permissions = True
        # The customer form enforces its own clear 8-character minimum. Avoid
        # Frappe's separate strength checker rejecting an otherwise valid form
        # after submission with only a generic error.
        user.flags.ignore_password_policy = True
        user.insert()
        if frappe.db.exists("Role", "Customer"):
            user.add_roles("Customer")
        frappe.db.commit()
        email_sent = False
        if frappe.db.exists("Email Account", {"enable_outgoing": 1}):
            try:
                store_url = frappe.utils.get_url()
                frappe.sendmail(
                    recipients=[email],
                    subject="تم إنشاء حسابك في المتجر",
                    message=f"<div dir='rtl'><h2>مرحبًا {frappe.utils.escape_html(first_name)}</h2><p>تم إنشاء حسابك كعميل بنجاح.</p><p><a href='{store_url}/customer-login'>تسجيل الدخول إلى المتجر</a></p></div>",
                    now=True,
                )
                email_sent = True
            except Exception:
                email_sent = False
        result = {"created": True, "email": email, "email_sent": email_sent, "message": "تم إنشاء حساب العميل بنجاح."}
    except Exception:
        frappe.log_error(title="Dukkani customer signup failed", message=frappe.get_traceback())
        frappe.db.rollback()
        result["detail"] = "تعذّر إنشاء الحساب. راجع البيانات وحاول مرة أخرى."
print("CUSTOMER_REGISTER_JSON:" + json.dumps(result, ensure_ascii=False))
'''


def register_customer(sub, payload):
    out = _run(_site_name(sub), CUSTOMER_REGISTER_CODE,
               infile="/tmp/customer_register_in.json", indata=payload)
    data = _marker(out, "CUSTOMER_REGISTER_JSON:")
    if data is None:
        raise RuntimeError("تعذّر إنشاء حساب العميل.")
    return data


CUSTOMER_LOGIN_CODE = r'''
import frappe, json
from frappe.utils.password import check_password
d = json.load(open("/tmp/customer_login_in.json", encoding="utf-8"))
email = (d.get("email") or "").strip().lower()
password = d.get("password") or ""
result = {"authenticated": False, "detail": "البريد الإلكتروني أو كلمة المرور غير صحيحة."}
if email and password and frappe.db.exists("User", email):
    user = frappe.get_doc("User", email)
    roles = set(frappe.get_roles(email))
    merchant_roles = {
        "System Manager", "Website Manager", "Merchant Owner",
        "Store Manager", "Store Staff", "Dukkani Store Owner",
    }
    # Customer auth is deliberately independent from the ERPNext Desk session.
    # A merchant account must never become a storefront customer implicitly.
    is_customer = user.user_type == "Website User" and "Customer" in roles
    if user.enabled and is_customer and not roles.intersection(merchant_roles):
        try:
            check_password(email, password)
            result = {"authenticated": True, "email": email, "name": user.full_name or user.first_name or email}
        except Exception:
            pass
print("CUSTOMER_LOGIN_JSON:" + json.dumps(result, ensure_ascii=False))
'''


def login_customer(sub, payload):
    out = _run(_site_name(sub), CUSTOMER_LOGIN_CODE,
               infile="/tmp/customer_login_in.json", indata=payload)
    data = _marker(out, "CUSTOMER_LOGIN_JSON:")
    if data is None:
        raise RuntimeError("تعذّر تسجيل دخول العميل.")
    return data
