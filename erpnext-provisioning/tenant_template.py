# ============================================================
#  Dukkani — قالب تهيئة التاجر (Tenant Template)
#  يُطبَّق على كل Site جديد بعد إنشائه مباشرة (الخطوة 4 في الفلو).
#
#  طريقة التشغيل (داخل الكونتينر عبر bench console):
#     bench --site <SITE> console < tenant_template.py
#  أو من سكريبت التجهيز provision_tenant.sh الذي يمرّر متغيّرات التاجر.
#
#  آمن للتكرار (Idempotent): إعادة تشغيله لا تُنشئ تكراراً.
#  كل القيم مستخرَجة من كود دكاني الفعلي — لا اختراع:
#    - العملة SAR            (orders.currency default 'SAR')
#    - الدولة السعودية / ZATCA Phase 2
#    - الأدوار               (CLAUDE.md: merchant_owner / store_manager / customer)
#    - بوابات الدفع          (Moyasar / Tabby / Tamara)
# ============================================================
import os
import re
import frappe

# ---- بيانات التاجر (تُمرَّر كمتغيّرات بيئة من سكريبت التجهيز) ----
MERCHANT_NAME = os.environ.get("MERCHANT_NAME", "Dukkani Merchant")
MERCHANT_ABBR = os.environ.get("MERCHANT_ABBR", "").strip() or "".join(
    w[0] for w in MERCHANT_NAME.split()[:3]
).upper() or "DKN"
MERCHANT_EMAIL = os.environ.get("MERCHANT_EMAIL", "owner@dukkani.ai")
MERCHANT_PASSWORD = os.environ.get("MERCHANT_PASSWORD", "")  # من فورم التسجيل
# الدولة/العملة تُمرَّر من التسجيل (كود الدولة → جنسية التاجر). الافتراضي السعودية.
_ENV_COUNTRY = os.environ.get("MERCHANT_COUNTRY")
COUNTRY = _ENV_COUNTRY or "Saudi Arabia"
# لكل دولة مدعومة: العملة + المنطقة الزمنية + نسبة الضريبة (من واقع كل بلد)
_LOCALE = {
    "Saudi Arabia": {"currency": "SAR", "tz": "Asia/Riyadh",   "vat": 15.0},
    "Egypt":        {"currency": "EGP", "tz": "Africa/Cairo",   "vat": 14.0},
    "Sudan":        {"currency": "SDG", "tz": "Africa/Khartoum", "vat": 0.0},
}
_loc = _LOCALE.get(COUNTRY, _LOCALE["Saudi Arabia"])
try:
    _existing_company = frappe.db.get_single_value("Global Defaults", "default_company")
    _existing_currency = (
        frappe.db.get_value("Company", _existing_company, "default_currency")
        if _existing_company else None
    )
except Exception:
    _existing_currency = None
CURRENCY = os.environ.get("MERCHANT_CURRENCY") or _existing_currency or _loc["currency"]
TIMEZONE = _loc["tz"]
VAT_RATE = _loc["vat"]
FY_START = os.environ.get("FY_START", "2026-01-01")
FY_END = os.environ.get("FY_END", "2026-12-31")

log = lambda msg: print(f"   • {msg}")
GENERIC_MERCHANT_NAMES = {"", "Dukkani Merchant", "Dukkani", "متجري"}
CUSTOMER_SIGNUP_HEAD_SCRIPT = """<script id="dukkani-custom-signup-link">
document.addEventListener("click", function (event) {
  var link = event.target.closest && event.target.closest(".sign-up-message a");
  if (!link || !document.querySelector("section.for-login")) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  window.location.assign("https://dukani.ai/signup");
}, true);
</script>"""


def merchant_display_name():
    """اسم المتجر للعرض: متغير التجهيز أولاً، ثم يوزر التاجر الحقيقي.

    بعض المواقع القديمة اتجهزت بالافتراضي `Dukkani Merchant`، بينما اسم
    التاجر موجود على User الحقيقي. نستخدمه لتصحيح اسم الشركة والهيدر العام.
    """
    if MERCHANT_NAME.strip() not in GENERIC_MERCHANT_NAMES:
        return MERCHANT_NAME.strip()
    if MERCHANT_EMAIL and MERCHANT_EMAIL not in ["owner@dukkani.ai", "Administrator"]:
        full_name = frappe.db.get_value("User", MERCHANT_EMAIL, "full_name")
        if full_name and full_name.strip() not in GENERIC_MERCHANT_NAMES:
            return full_name.strip()
    rows = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User"},
        fields=["name", "full_name"],
        limit_page_length=20,
    )
    for row in rows:
        if row.name in ["Administrator", "Guest", "owner@dukkani.ai"]:
            continue
        full_name = (row.full_name or "").strip()
        if full_name and full_name not in GENERIC_MERCHANT_NAMES:
            return full_name
    return MERCHANT_NAME.strip()


def ensure_prerequisites():
    """ماستر داتا يحتاجها إنشاء الشركة (تُنشأ عادةً في معالج الإعداد)."""
    if not frappe.db.exists("Warehouse Type", "Transit"):
        wt = frappe.new_doc("Warehouse Type")
        wt.name = "Transit"
        wt.insert(ignore_permissions=True)
        log("تم إنشاء Warehouse Type: Transit")


def ensure_company():
    """إنشاء شركة التاجر — ERPNext يُنشئ دليل الحسابات تلقائياً معها."""
    display_name = merchant_display_name()
    existing = frappe.db.get_value("Company", {"company_name": display_name})
    if existing:
        log(f"الشركة موجودة: {existing}")
        return existing
    company = frappe.new_doc("Company")
    company.company_name = display_name
    company.abbr = MERCHANT_ABBR
    company.default_currency = CURRENCY
    company.country = COUNTRY
    company.create_chart_of_accounts_based_on = "Standard Template"
    company.chart_of_accounts = "Standard"
    company.insert(ignore_permissions=True)
    log(f"تم إنشاء الشركة + دليل الحسابات: {company.name}")
    return company.name


def ensure_store_display_name():
    """تصحيح اسم الشركة الافتراضية لو لسه باسم دكاني العام."""
    target = merchant_display_name()
    company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    if not company or not target or target in GENERIC_MERCHANT_NAMES:
        return
    if company == target:
        return
    current_company_name = frappe.db.get_value("Company", company, "company_name") or company
    if current_company_name not in GENERIC_MERCHANT_NAMES and company not in GENERIC_MERCHANT_NAMES:
        return
    if frappe.db.exists("Company", target):
        gd = frappe.get_doc("Global Defaults")
        gd.default_company = target
        gd.save(ignore_permissions=True)
        return
    frappe.rename_doc("Company", company, target, force=True, ignore_permissions=True)
    log(f"تصحيح اسم المتجر في ERPNext: {target}")


def ensure_fiscal_year():
    if not frappe.db.exists("Fiscal Year", {"year_start_date": FY_START}):
        fy = frappe.new_doc("Fiscal Year")
        fy.year = FY_START[:4]
        fy.year_start_date = FY_START
        fy.year_end_date = FY_END
        fy.insert(ignore_permissions=True)
        log(f"تم إنشاء السنة المالية: {fy.year}")


def set_global_defaults(company):
    gd = frappe.get_doc("Global Defaults")
    gd.default_company = company
    gd.country = COUNTRY
    gd.default_currency = CURRENCY
    gd.save(ignore_permissions=True)
    ss = frappe.get_doc("System Settings")
    ss.language = ss.language or "en"
    ss.country = COUNTRY
    ss.time_zone = TIMEZONE
    ss.setup_complete = 1
    ss.save(ignore_permissions=True)
    # الفلاغ الحقيقي الذي يمنع معالج الإعداد في v16:
    # frappe.is_setup_complete() يفحص is_setup_complete على doctype "Installed Application"
    # لكل تطبيق مثبّت (frappe + erpnext). لا يكفي حقل System Settings وحده.
    frappe.db.sql("UPDATE `tabInstalled Application` SET is_setup_complete=1")
    frappe.db.set_default("desktop:home_page", "workspace")
    log("تم ضبط الإعدادات العامة + تخطّي معالج الإعداد (Installed Application).")


def ensure_customer_signup_enabled():
    """Keep public customer signup consistent on every merchant storefront."""
    if frappe.db.exists("DocType", "Website Settings"):
        ws = frappe.get_doc("Website Settings")
        ws.disable_signup = 0
        ws.hide_login = 0
        if hasattr(ws, "hide_footer_signup"):
            ws.hide_footer_signup = 0
        if hasattr(ws, "head_html"):
            current = ws.head_html or ""
            current = re.sub(
                r'\s*<script id="dukkani-custom-signup-link">.*?</script>\s*',
                "\n",
                current,
                flags=re.S,
            ).strip()
            ws.head_html = (
                f"{current}\n{CUSTOMER_SIGNUP_HEAD_SCRIPT}".strip()
                if current
                else CUSTOMER_SIGNUP_HEAD_SCRIPT
            )
        ws.save(ignore_permissions=True)
    if frappe.db.exists("DocType", "System Settings"):
        ss = frappe.get_doc("System Settings")
        if hasattr(ss, "disable_user_pass_login"):
            ss.disable_user_pass_login = 0
        if hasattr(ss, "login_with_email_link"):
            ss.login_with_email_link = 1
        ss.save(ignore_permissions=True)
    log("تم تفعيل تسجيل العملاء من صفحة دخول المتجر.")


def ensure_roles():
    """أدوار دكاني الثلاثة + صلاحياتها داخل موقع التاجر (مطابقة لتصميم دكاني القديم).
    Merchant Owner = كامل | Store Manager = بلا ماليات/حذف | Store Staff = أساسي."""
    from frappe.permissions import add_permission, update_permission_property
    for role in ["Merchant Owner", "Store Manager", "Store Staff"]:
        if not frappe.db.exists("Role", role):
            r = frappe.new_doc("Role")
            r.role_name = role
            r.desk_access = 1
            r.insert(ignore_permissions=True)
            log(f"تم إنشاء الدور: {role}")

    SUBMITTABLE = {"Sales Order", "Sales Invoice", "Delivery Note", "Payment Entry", "Quotation"}

    def grant(doctype, role, base):
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
    OPS = {"read": 1, "write": 1, "create": 1, "submit": 1}   # بلا حذف
    RW = {"read": 1, "write": 1, "create": 1}
    RO = {"read": 1}

    # Merchant Owner = كل الصلاحيات على مستندات المتجر
    for dt in ["Item", "Item Group", "Customer", "Sales Order", "Sales Invoice",
               "Delivery Note", "Payment Entry", "Pricing Rule", "Quotation"]:
        grant(dt, "Merchant Owner", FULL)
    # Store Manager = كل شيء ماعدا الماليات (Payment Entry) والحذف
    for dt in ["Item", "Item Group", "Customer", "Sales Order", "Sales Invoice",
               "Delivery Note", "Quotation", "Pricing Rule"]:
        grant(dt, "Store Manager", OPS)
    # Store Staff = عمليات أساسية (منتجات/طلبات/شحن)
    grant("Item", "Store Staff", RW)
    grant("Item Group", "Store Staff", RO)
    grant("Customer", "Store Staff", RO)
    grant("Sales Order", "Store Staff", {"read": 1, "write": 1, "submit": 1})
    grant("Delivery Note", "Store Staff", {"read": 1, "write": 1, "create": 1})
    log("تم ضبط صلاحيات الأدوار الثلاثة (Owner كامل / Manager بلا ماليات / Staff أساسي)")


def ensure_payment_modes(company):
    """بوابات الدفع المستخدمة في دكاني."""
    for mop in ["Moyasar", "Tabby", "Tamara"]:
        if not frappe.db.exists("Mode of Payment", mop):
            doc = frappe.new_doc("Mode of Payment")
            doc.mode_of_payment = mop
            doc.type = "General"
            doc.insert(ignore_permissions=True)
            log(f"تمت إضافة وسيلة دفع: {mop}")


def ensure_vat_template(company, abbr):
    """ضريبة القيمة المضافة حسب الدولة — حساب + قالب ضرائب مبيعات.
    السعودية 15% (ZATCA) / مصر 14% / السودان بلا ضريبة (نتخطّى)."""
    if not VAT_RATE:
        log(f"لا ضريبة قيمة مضافة في {COUNTRY} — تخطّي قالب الضريبة.")
        return
    tax_account = f"VAT {int(VAT_RATE)}% - {abbr}"
    if not frappe.db.exists("Account", tax_account):
        parent = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Tax", "is_group": 1},
        ) or frappe.db.get_value(
            "Account", {"company": company, "account_name": "Duties and Taxes"}
        )
        if parent:
            acc = frappe.new_doc("Account")
            acc.account_name = f"VAT {int(VAT_RATE)}%"
            acc.parent_account = parent
            acc.company = company
            acc.account_type = "Tax"
            acc.tax_rate = VAT_RATE
            acc.insert(ignore_permissions=True)
            log(f"تم إنشاء حساب الضريبة: {acc.name}")

    tmpl_name = f"VAT {int(VAT_RATE)}% - {abbr}"
    if frappe.db.exists("Account", tax_account) and not frappe.db.exists(
        "Sales Taxes and Charges Template", tmpl_name
    ):
        t = frappe.new_doc("Sales Taxes and Charges Template")
        t.title = f"VAT {int(VAT_RATE)}%"
        t.company = company
        t.append(
            "taxes",
            {
                "charge_type": "On Net Total",
                "account_head": tax_account,
                "description": f"VAT {int(VAT_RATE)}%",
                "rate": VAT_RATE,
            },
        )
        t.insert(ignore_permissions=True)
        log(f"تم إنشاء قالب ضريبة المبيعات: {t.name}")


def ensure_base_masters(company):
    """masters أساسية يُنشئها معالج الإعداد عادةً (ونحن نتخطاه) — بدونها لا يمكن البيع."""
    # وحدة قياس
    if not frappe.db.exists("UOM", "Nos"):
        frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)
        log("UOM: Nos")
    # أنواع حركات المخزون
    for setype in ["Material Receipt", "Material Issue", "Material Transfer"]:
        if not frappe.db.exists("Stock Entry Type", setype):
            d = frappe.new_doc("Stock Entry Type"); d.name = setype; d.purpose = setype
            d.insert(ignore_permissions=True)
    # أشجار التصنيف (جذر + ورقة)
    def _tree(dt, field, root, leaf, parent):
        if not frappe.db.exists(dt, root):
            d = frappe.new_doc(dt); d.set(field, root); d.is_group = 1
            d.insert(ignore_permissions=True)
        if leaf and not frappe.db.exists(dt, leaf):
            d = frappe.new_doc(dt); d.set(field, leaf); d.set(parent, root); d.is_group = 0
            d.insert(ignore_permissions=True)
    _tree("Item Group", "item_group_name", "All Item Groups", "Dukkani Products", "parent_item_group")
    _tree("Customer Group", "customer_group_name", "All Customer Groups", "Individual", "parent_customer_group")
    _tree("Territory", "territory_name", "All Territories", COUNTRY, "parent_territory")
    # قائمة أسعار البيع
    if not frappe.db.exists("Price List", "Standard Selling"):
        pl = frappe.new_doc("Price List"); pl.price_list_name = "Standard Selling"
        pl.selling = 1; pl.currency = CURRENCY
        pl.insert(ignore_permissions=True); log("Price List: Standard Selling")
    else:
        pl = frappe.get_doc("Price List", "Standard Selling")
        if pl.currency != CURRENCY:
            pl.currency = CURRENCY
            pl.save(ignore_permissions=True)
            log(f"تحديث عملة قائمة الأسعار: Standard Selling = {CURRENCY}")
    if frappe.db.exists("DocType", "Selling Settings"):
        ss = frappe.get_doc("Selling Settings")
        ss.selling_price_list = "Standard Selling"
        if hasattr(ss, "currency"):
            ss.currency = CURRENCY
        ss.save(ignore_permissions=True)
    # الحسابات الافتراضية للشركة (مطلوبة للفواتير والمخزون)
    comp = frappe.get_doc("Company", company)
    _acc = lambda frag: frappe.db.get_value(
        "Account", {"company": company, "account_name": frag, "is_group": 0}, "name")
    dmap = {
        "default_income_account": "Sales", "default_receivable_account": "Debtors",
        "default_expense_account": "Cost of Goods Sold", "default_inventory_account": "Stock In Hand",
        "stock_received_but_not_billed": "Stock Received But Not Billed",
        "stock_adjustment_account": "Stock Adjustment", "default_cash_account": "Cash",
    }
    ch = False
    for f, n in dmap.items():
        if not comp.get(f):
            a = _acc(n)
            if a:
                comp.set(f, a); ch = True
    if ch:
        comp.save(ignore_permissions=True)
    log("تم تجهيز الـ masters الأساسية (UOM/مخزون/تصنيفات/أسعار/حسابات) — التاجر جاهز للبيع.")


def ensure_dukkani_look():
    """شكل دكاني: إخفاء الموديولات غير المتعلّقة بالمتجر + Workspace رئيسي للتاجر.
    كله إعدادات قياسية (Workspace) — بلا Custom Fields."""
    import json
    # 1) إخفاء موديولات لا يحتاجها تاجر تجزئة (retail)
    hide = ["Build", "Assets", "Subcontracting", "Manufacturing", "Quality",
            "Projects", "Support", "Website", "Welcome Workspace"]
    hidden = 0
    for w in hide:
        if frappe.db.exists("Workspace", w) and not frappe.db.get_value("Workspace", w, "is_hidden"):
            frappe.db.set_value("Workspace", w, "is_hidden", 1); hidden += 1
    if hidden:
        log(f"إخفاء {hidden} موديول غير متعلّق بالمتجر")

    # 2) Workspace رئيسي "Dukkani" باختصارات لأهم شاشات التاجر
    if not frappe.db.exists("Workspace", "Dukkani"):
        shortcuts = [
            ("Sales Invoice", "فواتير المبيعات", "Green"),
            ("Sales Order", "طلبات البيع", "Blue"),
            ("Item", "المنتجات", "Orange"),
            ("Customer", "العملاء", "Cyan"),
            ("Payment Entry", "المدفوعات", "Purple"),
        ]
        content = [{"id": "dkn_hdr", "type": "header",
                    "data": {"text": '<span class="h4"><b>متجر دكاني</b></span>', "col": 12}}]
        for _, label, _c in shortcuts:
            content.append({"id": "sc_" + label, "type": "shortcut",
                            "data": {"shortcut_name": label, "col": 3}})
        w = frappe.new_doc("Workspace")
        w.name = "Dukkani"; w.label = "Dukkani"; w.title = "Dukkani"
        w.public = 1; w.is_hidden = 0; w.icon = "retail"; w.sequence_id = 1
        for link, label, color in shortcuts:
            w.append("shortcuts", {"type": "DocType", "link_to": link, "label": label, "color": color})
        w.content = json.dumps(content)
        w.insert(ignore_permissions=True)
        log("إنشاء Workspace رئيسي للتاجر: Dukkani")

    # 3) حجب الموديولات غير المتعلّقة بالمتجر على مستوى الـ Module (اللي بتظهر في شبكة التطبيقات)
    block = ["Manufacturing", "Subcontracting", "Assets", "Projects", "Quality Management",
             "Support", "Maintenance", "EDI", "Telephony", "Bulk Transaction", "Website"]
    u = frappe.get_doc("User", "Administrator")
    have = {b.module for b in u.block_modules}
    n = 0
    for m in block:
        if frappe.db.exists("Module Def", m) and m not in have:
            u.append("block_modules", {"module": m}); n += 1
    if n:
        u.save(ignore_permissions=True)
        log(f"حجب {n} موديول من شبكة التطبيقات")
    # 4) تفعيل نطاق Retail (يخفي الموديولات الصناعية القياسية)
    if frappe.db.exists("Domain", "Retail"):
        ds = frappe.get_doc("Domain Settings")
        if "Retail" not in [d.domain for d in ds.active_domains]:
            ds.set("active_domains", [])
            ds.append("active_domains", {"domain": "Retail"})
            ds.save(ignore_permissions=True)
            log("تفعيل نطاق Retail")


def ensure_dukkani_grid():
    """تنظيف شبكة التطبيقات في ERPNext v16 (Workspace Sidebar).

    في v16 اتغيّر نظام التنقل بالكامل: الشبكة/السايدبار بتتبني من دوكتايب
    'Workspace Sidebar'، وبتعرض أيقونة أي موديول المستخدم يقدر يقرأ فيه أي عنصر.
    لأن أدوار المخزون/الحسابات بتدّي قراءة على تقارير ودوكتايبس مشتركة، بتظهر
    موديولات زيادة (Manufacturing/Assets/Quality/Subcontracting...) رغم إخفاء
    الـ Workspace وحجب الموديول. الحل الحاسم (بلا custom fields، ومستقل عن الأدوار):
    نخلّي الـ Workspace Sidebar للموديولات غير المرغوبة تحتوي على 'Section Break'
    فقط بلا أي عنصر حقيقي → القاعدة القياسية في frappe بتخفيها، وكمان وجود السجل
    بيمنع frappe من إعادة توليدها تلقائيًا من Module Def."""
    if not frappe.db.exists("DocType", "Workspace Sidebar"):
        return  # إصدار أقدم من v16 — الشبكة بتتحكم بآليات ensure_dukkani_look أعلاه

    # الموديولات اللي نخفيها من الشبكة (ضوضاء تجارية + موديولات إطار داخلية)
    hide_grid = [
        "Assets", "Manufacturing", "Quality", "Quality Management", "Subcontracting",
        "Support", "Projects", "Maintenance", "Telephony", "Regional", "Banking",
        "Budget", "Payments", "Subscription", "Taxes", "Share Management", "Automation",
        "Build", "Core", "Desk", "Email", "Geo", "Printing", "System", "Utilities",
        "EDI", "Bulk Transaction", "Communication", "Contacts", "Workflow", "Portal",
        "Website",
    ]
    n = 0
    for title in hide_grid:
        try:
            if frappe.db.exists("Workspace Sidebar", title):
                d = frappe.get_doc("Workspace Sidebar", title)
                # لو مخفية بالفعل (Section Break فقط) نتخطاها
                if all(it.type == "Section Break" for it in d.items):
                    continue
            else:
                d = frappe.new_doc("Workspace Sidebar"); d.title = title
            d.for_user = None
            d.items = []
            d.append("items", {"type": "Section Break", "label": "_hidden", "idx": 1})
            d.flags.ignore_links = True
            d.save(ignore_permissions=True)
            n += 1
        except Exception as e:
            log(f"تعذّر إخفاء {title} من الشبكة: {e}")
    if n:
        log(f"تنظيف شبكة التطبيقات (v16): إخفاء {n} موديول غير متعلّق بالمتجر")

    # أيقونة 'دكاني' كأول عنصر في الشبكة (اختصارات أهم شاشات التاجر)
    if not frappe.db.exists("Workspace Sidebar", "Dukkani"):
        items = [
            ("Home",             "Dukkani",       "Workspace", "wallpaper"),
            ("فواتير المبيعات",  "Sales Invoice", "DocType",   "file-text"),
            ("طلبات البيع",      "Sales Order",   "DocType",   "shopping-cart"),
            ("المنتجات",         "Item",          "DocType",   "package"),
            ("العملاء",          "Customer",      "DocType",   "users"),
            ("المدفوعات",        "Payment Entry", "DocType",   "credit-card"),
        ]
        d = frappe.new_doc("Workspace Sidebar")
        d.title = "Dukkani"; d.header_icon = "retail"; d.for_user = None
        for idx, (label, link_to, link_type, icon) in enumerate(items):
            d.append("items", {"label": label, "link_to": link_to,
                               "link_type": link_type, "type": "Link",
                               "icon": icon, "idx": idx})
        d.flags.ignore_links = True
        d.save(ignore_permissions=True)
        log("إنشاء أيقونة 'دكاني' في شبكة التطبيقات")


def ensure_role_profiles():
    """أدوار موحّدة تجمّع أدوار ERPNext القياسية (بلا هندسة صلاحيات يدوية، بلا custom fields)."""
    profiles = {
        "Dukkani Store Owner": ["Sales Manager", "Stock Manager", "Accounts Manager", "Item Manager"],
        "Dukkani Store Manager": ["Sales User", "Stock Manager", "Item Manager"],  # بلا محاسبة
        "Dukkani Cashier": ["Sales User"],
        "Dukkani Inventory": ["Stock User"],
        "Dukkani Accountant": ["Accounts User", "Accounts Manager"],
    }
    made = 0
    for pname, roles in profiles.items():
        if frappe.db.exists("Role Profile", pname):
            continue
        rp = frappe.new_doc("Role Profile"); rp.role_profile = pname
        for r in roles:
            if frappe.db.exists("Role", r):
                rp.append("roles", {"role": r})
        rp.insert(ignore_permissions=True); made += 1
    if made:
        log(f"إنشاء {made} Role Profile موحّد (المالك/المدير بلا ماليات/كاشير/مخزون/محاسب)")


def ensure_owner_user():
    """ينشئ يوزر المالك للتاجر (من بيانات فورم التسجيل) بدور Dukkani Store Owner.

    ده هو الدخول الفعلي للتاجر — مش Administrator (اللي هو حساب BDC الداخلي للدعم).
    التاجر بيدخل بإيميله فيلاقي الشكل النضيف تلقائيًا (الأدوار المحدودة = شبكة نضيفة).
    آمن للتكرار: لو اليوزر موجود بنحدّث دوره وحالته بس."""
    if not MERCHANT_EMAIL:
        log("تخطّي إنشاء يوزر المالك (لا يوجد MERCHANT_EMAIL).")
        return

    PROFILE = "Dukkani Store Owner"
    # الأدوار اللي هتتطبّق (من الـ Role Profile لو موجود، وإلا القائمة الافتراضية)
    if frappe.db.exists("Role Profile", PROFILE):
        roles = [r.role for r in frappe.get_doc("Role Profile", PROFILE).roles]
    else:
        roles = ["Sales Manager", "Stock Manager", "Accounts Manager", "Item Manager"]

    exists = frappe.db.exists("User", MERCHANT_EMAIL)
    u = frappe.get_doc("User", MERCHANT_EMAIL) if exists else frappe.new_doc("User")
    if not exists:
        u.email = MERCHANT_EMAIL
        parts = MERCHANT_NAME.split()
        u.first_name = parts[0] if parts else "Store"
        if len(parts) > 1:
            u.last_name = " ".join(parts[1:])
        u.send_welcome_email = 0
        if MERCHANT_PASSWORD:
            u.new_password = MERCHANT_PASSWORD
    u.enabled = 1
    u.user_type = "System User"       # مستخدم مكتب (Desk) عشان يدير متجره
    u.language = "ar"
    u.time_zone = TIMEZONE
    # ضبط الدور: نمسح الأدوار القديمة ونطبّق أدوار التاجر فقط (بلا System Manager)
    have = {r.role for r in u.get("roles", [])}
    for r in roles:
        if r not in have and frappe.db.exists("Role", r):
            u.append("roles", {"role": r})
    # ربط الـ Role Profile كمان (لو الحقل موجود في هذا الإصدار)
    if u.meta.has_field("role_profile_name") and frappe.db.exists("Role Profile", PROFILE):
        u.role_profile_name = PROFILE
    u.flags.ignore_permissions = True
    u.flags.ignore_password_policy = True   # نقبل باسورد التاجر زي ما هو (بلا فحص قوة)
    u.save(ignore_permissions=True)
    # إسناد دور Merchant Owner (إدراج مباشر لتفادي تنظيف الأدوار عند حفظ المستخدم)
    if not frappe.db.exists("Has Role", {"parent": MERCHANT_EMAIL, "role": "Merchant Owner"}):
        frappe.get_doc({"doctype": "Has Role", "parent": MERCHANT_EMAIL, "parenttype": "User",
                        "parentfield": "roles", "role": "Merchant Owner"}).insert(ignore_permissions=True)
    log(f"{'تحديث' if exists else 'إنشاء'} يوزر المالك: {MERCHANT_EMAIL} (دور: Merchant Owner)")


def ensure_naming_series():
    """ترقيم بصيغة دكاني عبر Property Setter (تعديل خاصية حقل قياسي — ليس custom field)."""
    from frappe.custom.doctype.property_setter.property_setter import make_property_setter
    series = {
        "Sales Order": "DKN-ORD-.YYYY.-",
        "Sales Invoice": "DKN-INV-.YYYY.-",
        "Payment Entry": "DKN-PAY-.YYYY.-",
        "Delivery Note": "DKN-DN-.YYYY.-",
    }
    for dt, prefix in series.items():
        if not frappe.db.exists("DocType", dt):
            continue
        make_property_setter(dt, "naming_series", "options", prefix, "Text",
                             validate_fields_for_doctype=False)
        make_property_setter(dt, "naming_series", "default", prefix, "Text",
                             validate_fields_for_doctype=False)
    log("ضبط الترقيم بصيغة دكاني (DKN-INV / DKN-ORD / DKN-PAY)")


def ensure_item_group():
    if frappe.db.exists("Item Group", "Dukkani Products"):
        return
    root = frappe.db.get_value("Item Group", {"is_group": 1, "parent_item_group": ["in", ["", None]]})
    if not root:
        groups = frappe.get_all("Item Group", filters={"is_group": 1}, limit=1)
        root = groups[0].name if groups else None
    if not root:
        log("تخطّي مجموعة الأصناف (لا يوجد جذر Item Group بعد).")
        return
    g = frappe.new_doc("Item Group")
    g.item_group_name = "Dukkani Products"
    g.parent_item_group = root
    g.is_group = 0
    g.insert(ignore_permissions=True)
    log("تمت إضافة مجموعة أصناف: Dukkani Products")


DASHBOARD_SCRIPT = r'''
# داشبورد الموبايل — تجميعة في نداء واحد.
# التطبيق مش بيقدر يجمّع دي بنفسه: كان هيجيب كل الطلبات ويحسب محلياً.
#
# ⚠️ بيشتغل في بيئة safe_exec المقيدة — مفيش import. المتاح:
#    frappe.db.sql / frappe.get_all / frappe.utils / frappe.response

period = (frappe.form_dict.get("period") or "month").lower()
if period not in ("day", "week", "month", "year"):
    period = "month"

today = frappe.utils.nowdate()
starts = {
    "day":   frappe.utils.add_days(today, -1),
    "week":  frappe.utils.add_days(today, -7),
    "month": frappe.utils.add_months(today, -1),
    "year":  frappe.utils.add_months(today, -12),
}
start = starts[period]
# الفترة السابقة بنفس الطول — عشان نحسب نسبة التغيّر
span = frappe.utils.date_diff(today, start)
prev_start = frappe.utils.add_days(start, -span)

def pct_change(now, before):
    """نسبة التغيّر. None لو مفيش أساس نقارن بيه — الشاشة تخفي المؤشر
    بدل ما تعرض +100% وهمية لأول فترة."""
    if not before:
        return None
    return round(((now - before) / before) * 100, 1)

# docstatus=1 = مُرحَّل. بنستبعد المسودات (0) والملغي (2) —
# دول مش مبيعات حقيقية.
# RestrictedPython بيمنع فك التغليف (a, b = ...) — بنرجّع dict ونفهرس.
def totals_between(frm, to):
    r = frappe.db.sql("""
        SELECT COALESCE(SUM(grand_total), 0), COUNT(*)
        FROM `tabSales Order`
        WHERE docstatus = 1 AND transaction_date BETWEEN %s AND %s
    """, (frm, to))
    if not r:
        return {"sales": 0.0, "orders": 0}
    return {"sales": float(r[0][0] or 0), "orders": int(r[0][1] or 0)}

cur = totals_between(start, today)
prev = totals_between(prev_start, start)

def new_customers_between(frm, to):
    r = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabCustomer`
        WHERE DATE(creation) BETWEEN %s AND %s
    """, (frm, to))
    return int(r[0][0] or 0) if r else 0

customers = new_customers_between(start, today)
prev_customers = new_customers_between(prev_start, start)

# «تحت التنفيذ» = مُرحَّل ولسه محتاج شغل. مش مقيّد بالفترة —
# دي حالة حالية مش مقياس فترة، فمفيش تغيّر تتقارن بيه.
pending = frappe.db.sql("""
    SELECT COUNT(*) FROM `tabSales Order`
    WHERE docstatus = 1
      AND status IN ('To Deliver and Bill', 'To Deliver', 'To Bill')
""")
pending_count = int(pending[0][0] or 0) if pending else 0

top = frappe.db.sql("""
    SELECT soi.item_code, soi.item_name, i.image,
           SUM(soi.qty), SUM(soi.amount)
    FROM `tabSales Order Item` soi
    JOIN `tabSales Order` so ON so.name = soi.parent
    LEFT JOIN `tabItem` i ON i.name = soi.item_code
    WHERE so.docstatus = 1 AND so.transaction_date BETWEEN %s AND %s
    GROUP BY soi.item_code, soi.item_name, i.image
    ORDER BY SUM(soi.amount) DESC
    LIMIT 4
""", (start, today))

# الرسم اليومي له فلتر مستقل عن فترة كروت المؤشرات.
chart_start = frappe.form_dict.get("chart_from") or frappe.utils.add_days(today, -29)
chart_end = frappe.form_dict.get("chart_to") or today
if frappe.utils.date_diff(chart_end, chart_start) < 0:
    frappe.throw("تاريخ النهاية يجب ألا يسبق تاريخ البداية")

daily_rows = frappe.db.sql("""
    SELECT transaction_date, COALESCE(SUM(grand_total), 0), COUNT(*)
    FROM `tabSales Order`
    WHERE docstatus = 1 AND transaction_date BETWEEN %s AND %s
    GROUP BY transaction_date
    ORDER BY transaction_date ASC
""", (chart_start, chart_end))
daily_sales = []
daily_sales_total = 0.0
for d in (daily_rows or []):
    value = float(d[1] or 0)
    daily_sales_total += value
    daily_sales.append({
        "date": str(d[0] or ""),
        "sales": value,
        "orders": int(d[2] or 0),
    })

# العملة من الشركة — مش ثابتة. نور مصرية (EGP)، والقالب القديم
# كان بيفترض SAR.
company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

frappe.response["message"] = {
    "period": period,
    "currency": currency,
    "total_sales":     {"value": cur["sales"],  "change": pct_change(cur["sales"], prev["sales"])},
    "total_orders":    {"value": cur["orders"], "change": pct_change(cur["orders"], prev["orders"])},
    "total_customers": {"value": customers,      "change": pct_change(customers, prev_customers)},
    "pending_orders":  {"value": pending_count,  "change": None},
    "daily_sales": daily_sales,
    "daily_sales_total": daily_sales_total,
    "top_products": [
        {"item_code": t[0], "name": t[1],
         "image": t[2],
         "qty": float(t[3] or 0), "revenue": float(t[4] or 0)}
        for t in (top or [])
    ],
}
'''


ANALYTICS_SCRIPT = r'''
# التحليلات والتقارير — مؤشرات أعمق من ERPNext Sales Order.
period = (frappe.form_dict.get("period") or "month").lower()
if period not in ("day", "week", "month", "year"):
    period = "month"

today = frappe.utils.nowdate()
custom_from = frappe.form_dict.get("from")
custom_to = frappe.form_dict.get("to")
starts = {
    "day": frappe.utils.add_days(today, -1),
    "week": frappe.utils.add_days(today, -7),
    "month": frappe.utils.add_months(today, -1),
    "year": frappe.utils.add_months(today, -12),
}
start = custom_from or starts[period]
end = custom_to or today
if frappe.utils.date_diff(end, start) < 0:
    frappe.throw("تاريخ النهاية يجب ألا يسبق تاريخ البداية")
if custom_from and custom_to:
    period = "custom"
span = frappe.utils.date_diff(end, start) + 1
prev_end = frappe.utils.add_days(start, -1)
prev_start = frappe.utils.add_days(prev_end, -(span - 1))

def pct_change(now, before):
    if not before:
        return None
    return round(((now - before) / before) * 100, 1)

def totals_between(frm, to):
    r = frappe.db.sql("""
        SELECT COALESCE(SUM(grand_total), 0), COUNT(*)
        FROM `tabSales Order`
        WHERE docstatus = 1 AND transaction_date BETWEEN %s AND %s
    """, (frm, to))
    sales = float(r[0][0] or 0) if r else 0
    orders = int(r[0][1] or 0) if r else 0
    avg = sales / orders if orders else 0
    return {"sales": sales, "orders": orders, "average": avg}

cur = totals_between(start, end)
prev = totals_between(prev_start, prev_end)

def new_customers_between(frm, to):
    r = frappe.db.sql("""
        SELECT COUNT(*) FROM `tabCustomer`
        WHERE DATE(creation) BETWEEN %s AND %s
    """, (frm, to))
    return int(r[0][0] or 0) if r else 0

customers = new_customers_between(start, end)
prev_customers = new_customers_between(prev_start, prev_end)

pending = frappe.db.sql("""
    SELECT COUNT(*) FROM `tabSales Order`
    WHERE docstatus = 1
      AND status IN ('To Deliver and Bill', 'To Deliver', 'To Bill')
""")
pending_count = int(pending[0][0] or 0) if pending else 0

status_labels = {
    "Draft": "مسودة",
    "To Deliver and Bill": "بانتظار التنفيذ",
    "To Deliver": "بانتظار التسليم",
    "To Bill": "بانتظار الفوترة",
    "Completed": "مكتملة",
    "Closed": "مغلقة",
    "Cancelled": "ملغية",
}
status_rows = frappe.db.sql("""
    SELECT status, COUNT(*)
    FROM `tabSales Order`
    WHERE transaction_date BETWEEN %s AND %s
    GROUP BY status
    ORDER BY COUNT(*) DESC
""", (start, end))
statuses = []
for s in (status_rows or []):
    raw = s[0] or ""
    statuses.append({
        "status": raw,
        "label": status_labels.get(raw) or raw,
        "count": int(s[1] or 0),
    })

top = frappe.db.sql("""
    SELECT soi.item_code, soi.item_name, i.image,
           SUM(soi.qty), SUM(soi.amount)
    FROM `tabSales Order Item` soi
    JOIN `tabSales Order` so ON so.name = soi.parent
    LEFT JOIN `tabItem` i ON i.name = soi.item_code
    WHERE so.docstatus = 1 AND so.transaction_date BETWEEN %s AND %s
    GROUP BY soi.item_code, soi.item_name, i.image
    ORDER BY SUM(soi.amount) DESC
    LIMIT 5
""", (start, end))

daily_rows = frappe.db.sql("""
    SELECT transaction_date, COALESCE(SUM(grand_total), 0), COUNT(*)
    FROM `tabSales Order`
    WHERE docstatus = 1 AND transaction_date BETWEEN %s AND %s
    GROUP BY transaction_date
    ORDER BY transaction_date ASC
    LIMIT 30
""", (start, end))
daily_sales = []
for d in (daily_rows or []):
    daily_sales.append({
        "date": str(d[0] or ""),
        "sales": float(d[1] or 0),
        "orders": int(d[2] or 0),
    })

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

frappe.response["message"] = {
    "period": period,
    "currency": currency,
    "sales": {"value": cur["sales"], "change": pct_change(cur["sales"], prev["sales"])},
    "orders": {"value": cur["orders"], "change": pct_change(cur["orders"], prev["orders"])},
    "average_order": {"value": cur["average"], "change": pct_change(cur["average"], prev["average"])},
    "customers": {"value": customers, "change": pct_change(customers, prev_customers)},
    "pending_orders": {"value": pending_count, "change": None},
    "statuses": statuses,
    "daily_sales": daily_sales,
    "top_products": [
        {"item_code": t[0], "name": t[1], "image": t[2],
         "qty": float(t[3] or 0), "revenue": float(t[4] or 0)}
        for t in (top or [])
    ],
}
'''


PRODUCTS_SCRIPT = r'''
# قائمة منتجات الموبايل — الأصناف + أسعارها في نداء واحد.
# الأسعار في doctype "Item Price" مش على الصنف نفسه (standard_rate أصفار)،
# فـ /api/resource/Item العادي كان هيرجّع منتجات بلا أسعار.
#
# ⚠️ بيئة safe_exec المقيدة: مفيش import، مفيش أسماء بـ _، مفيش فك تغليف.

page = frappe.utils.cint(frappe.form_dict.get("page") or 1)
if page < 1:
    page = 1
size = 20
start = (page - 1) * size

search = (frappe.form_dict.get("search") or "").strip()
status = (frappe.form_dict.get("status") or "").strip()
conds = "i.has_variants = 0"
args = []
if search:
    conds = conds + " AND (i.item_name LIKE %s OR i.item_code LIKE %s)"
    like = "%" + search + "%"
    args.append(like)
    args.append(like)
if status == "active":
    conds = conds + " AND i.disabled = 0"
elif status == "draft":
    conds = conds + " AND i.disabled = 1"

# الاستعلام بيتبني بدمج نصوص — RestrictedPython بيمنع .format().
# الشروط ثابتة أو %s (مش قيم مستخدم)، والقيم كلها بتتمرّر كباراميترات.
# سعر البيع من Item Price في subquery عشان المنتج من غير سعر يفضل يظهر.
list_sql = (
    "SELECT i.name, i.item_name, i.item_code, i.item_group, i.image, i.stock_uom, "
    "i.description, i.disabled, i.is_stock_item, i.weight_per_unit, "
    "(SELECT ib.barcode FROM `tabItem Barcode` ib WHERE ib.parent = i.name "
    " ORDER BY ib.idx ASC LIMIT 1) AS barcode, "
    "(SELECT SUM(b.actual_qty) FROM `tabBin` b WHERE b.item_code = i.item_code) AS stock_qty, "
    "(SELECT ip.price_list_rate FROM `tabItem Price` ip "
    " WHERE ip.item_code = i.item_code AND ip.selling = 1 "
    " ORDER BY ip.valid_from DESC LIMIT 1) AS rate "
    "FROM `tabItem` i WHERE " + conds + " "
    "ORDER BY i.modified DESC LIMIT %s OFFSET %s"
)
rows = frappe.db.sql(list_sql, tuple(args) + (size, start), as_dict=True)

count_sql = "SELECT COUNT(*) FROM `tabItem` i WHERE " + conds
total_row = frappe.db.sql(count_sql, tuple(args))
total = int(total_row[0][0] or 0) if total_row else 0

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

items = []
for r in rows:
    stock_qty = float(r.get("stock_qty") or 0)
    if status == "out_of_stock" and stock_qty > 0:
        continue
    items.append({
        "id": r.get("name"),
        "item_code": r.get("item_code"),
        "name": r.get("item_name"),
        "category": r.get("item_group"),
        "price": float(r.get("rate") or 0),
        "image": r.get("image"),          # نسبي (/files/…) — العميل بيركّب الـ base
        "uom": r.get("stock_uom"),
        "description": r.get("description"),
        "disabled": int(r.get("disabled") or 0),
        "sku": r.get("item_code"),
        "barcode": r.get("barcode"),
        "weight": float(r.get("weight_per_unit") or 0) or None,
        "stock_qty": stock_qty,
        "track_inventory": int(r.get("is_stock_item") or 0),
    })

frappe.response["message"] = {
    "currency": currency,
    "items": items,
    "pagination": {
        "page": page,
        "size": size,
        "total": total,
        "has_more": (start + len(items)) < total,
    },
}
'''


SAVE_PRODUCT_SCRIPT = r'''
# حفظ منتج الموبايل — إنشاء أو تعديل Item + سعر البيع في Item Price.
# ⚠️ safe_exec: مفيش import، مفيش أسماء بـ _، مفيش فك تغليف، مفيش .format().
# بصلاحيات التاجر العادية — الموقع بتاعه.

item_id = (frappe.form_dict.get("id") or "").strip()
name = (frappe.form_dict.get("name") or "").strip()
group = (frappe.form_dict.get("item_group") or "").strip()
desc = frappe.form_dict.get("description")
image = (frappe.form_dict.get("image") or "").strip()
price = frappe.utils.flt(frappe.form_dict.get("price"))
disabled = frappe.utils.cint(frappe.form_dict.get("disabled"))
sku = (frappe.form_dict.get("sku") or "").strip()
barcode = (frappe.form_dict.get("barcode") or "").strip()
weight = frappe.utils.flt(frappe.form_dict.get("weight"))
track_inventory = frappe.utils.cint(frappe.form_dict.get("track_inventory"))
stock_value = frappe.form_dict.get("stock_qty")
stock_qty = None
if stock_value is not None and str(stock_value).strip() != "":
    stock_qty = frappe.utils.flt(stock_value)

if not name:
    frappe.throw("اسم المنتج مطلوب")
if price <= 0:
    frappe.throw("السعر يجب أن يكون أكبر من صفر")

# تصنيف صالح لازم — لو مفيش، استخدم أول تصنيف ورقي أو الجذر.
if not group:
    group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"

uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos"

if item_id:
    doc = frappe.get_doc("Item", item_id)
    doc.item_name = name
    doc.item_group = group
    doc.disabled = disabled
    if desc is not None:
        doc.description = desc
    if image:
        doc.image = image
    if weight > 0:
        doc.weight_per_unit = weight
        doc.weight_uom = "Kg"
    if barcode:
        doc.set("barcodes", [])
        doc.append("barcodes", {"barcode": barcode})
    doc.save()
else:
    item_code = sku if sku else "MOB-" + frappe.utils.generate_hash(length=10)
    if frappe.db.exists("Item", item_code):
        frappe.throw("SKU مستخدم بالفعل")
    doc = frappe.get_doc({
        "doctype": "Item",
        "item_code": item_code,
        "item_name": name,
        "item_group": group,
        "stock_uom": uom,
        "is_stock_item": track_inventory,
        "disabled": disabled,
        "description": desc,
    })
    if image:
        doc.image = image
    if weight > 0:
        doc.weight_per_unit = weight
        doc.weight_uom = "Kg"
    if barcode:
        doc.append("barcodes", {"barcode": barcode})
    doc.insert()

code = doc.name
track_inventory = int(doc.is_stock_item or 0)

# كمية المخزون الظاهرة في الموبايل. بنكتبها في Bin الخاص بأول مخزن ورقي
# للمتجر، عشان قائمة المنتجات والتفاصيل ترجع نفس الرقم بدل صفر دائم.
if stock_qty is not None:
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
    if warehouse:
        existing_bin = frappe.db.get_value("Bin", {"item_code": code, "warehouse": warehouse}, "name")
        if existing_bin:
            frappe.db.set_value("Bin", existing_bin, {
                "actual_qty": stock_qty,
                "projected_qty": stock_qty,
            })
        else:
            bin_doc = frappe.get_doc({
                "doctype": "Bin",
                "item_code": code,
                "warehouse": warehouse,
                "actual_qty": stock_qty,
                "projected_qty": stock_qty,
            })
            bin_doc.insert(ignore_permissions=True)

# سعر البيع في Item Price (upsert) — قائمة أسعار البيع الافتراضية.
# إنشاء/قراءة Item Price محصور في Sales Master Manager؛ التاجر معندوش الدور ده.
# بنكتب بـ ignore_permissions — أأمن من إعطاء التاجر دور يعدّل كل الأسعار في الويب.
# كل متجر Site منفصل، فالسعر ده بتاع صنف التاجر نفسه ومفيش تداخل.
price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name") or "Standard Selling"
existing_price = frappe.db.get_value(
    "Item Price", {"item_code": code, "selling": 1, "price_list": price_list}, "name")
if existing_price:
    ip = frappe.get_doc("Item Price", existing_price)
    ip.price_list_rate = price
    ip.save(ignore_permissions=True)
else:
    ip = frappe.get_doc({
        "doctype": "Item Price",
        "item_code": code,
        "price_list": price_list,
        "selling": 1,
        "price_list_rate": price,
    })
    ip.insert(ignore_permissions=True)

frappe.response["message"] = {
    "id": doc.name,
    "item_code": doc.item_code,
    "name": doc.item_name,
    "category": doc.item_group,
    "price": price,
    "image": doc.image,
    "uom": doc.stock_uom,
    "description": doc.description,
    "disabled": int(doc.disabled or 0),
    "sku": doc.item_code,
    "barcode": barcode,
    "weight": float(doc.weight_per_unit or 0) or None,
    "stock_qty": stock_qty if stock_qty is not None else 0,
    "track_inventory": int(doc.is_stock_item or 0),
}
'''


PRODUCT_STATUS_SCRIPT = r'''
# تغيير حالة ظهور المنتج فقط من تطبيق الموبايل.
# ده مقصود يكون أخف من حفظ المنتج الكامل، عشان الإخفاء/النشر مايلمسش
# السعر أو المخزون أو الصورة أو حقول ERPNext التي قد تكون مرتبطة بمعاملات.
item_id = (frappe.form_dict.get("id") or "").strip()
disabled = frappe.utils.cint(frappe.form_dict.get("disabled"))

if not item_id:
    frappe.throw("المنتج مطلوب")
if not frappe.db.exists("Item", item_id):
    frappe.throw("المنتج غير موجود")

frappe.db.set_value("Item", item_id, "disabled", disabled)

doc = frappe.get_doc("Item", item_id)
price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name") or "Standard Selling"
price = frappe.db.get_value(
    "Item Price", {"item_code": doc.name, "selling": 1, "price_list": price_list}, "price_list_rate")
if price is None:
    price = 0

stock_qty = 0
bin_row = frappe.db.sql(
    "SELECT SUM(actual_qty) AS qty FROM `tabBin` WHERE item_code=%s",
    (doc.name,), as_dict=True)
if bin_row:
    stock_qty = float(bin_row[0].get("qty") or 0)

barcode = None
barcode_rows = doc.get("barcodes") or []
if barcode_rows:
    barcode = barcode_rows[0].barcode

frappe.response["message"] = {
    "id": doc.name,
    "item_code": doc.item_code,
    "name": doc.item_name,
    "category": doc.item_group,
    "price": float(price or 0),
    "image": doc.image,
    "uom": doc.stock_uom,
    "description": doc.description,
    "disabled": int(doc.disabled or 0),
    "sku": doc.item_code,
    "barcode": barcode,
    "weight": float(doc.weight_per_unit or 0) or None,
    "stock_qty": stock_qty,
    "track_inventory": int(doc.is_stock_item or 0),
}
'''


ITEM_GROUPS_SCRIPT = r'''
# تصنيفات المنتجات لملء الـ dropdown — الأوراق فقط (مش مجموعات الشجرة).
rows = frappe.get_all("Item Group",
    filters={"is_group": 0},
    fields=["name"],
    order_by="name asc")
frappe.response["message"] = [r.get("name") for r in rows]
'''


SAVE_ITEM_GROUP_SCRIPT = r'''
# إنشاء تصنيف منتج من تطبيق الموبايل.
name = (frappe.form_dict.get("name") or "").strip()
if not name:
    frappe.throw("اسم التصنيف مطلوب")

if frappe.db.exists("Item Group", name):
    frappe.response["message"] = {"name": name}
else:
    parent = "All Item Groups" if frappe.db.exists("Item Group", "All Item Groups") else None
    if not parent:
        parent = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
    doc = frappe.get_doc({
        "doctype": "Item Group",
        "item_group_name": name,
        "parent_item_group": parent,
        "is_group": 0,
    })
    doc.insert(ignore_permissions=True)
    frappe.response["message"] = {"name": doc.name}
'''


WAREHOUSES_SCRIPT = r'''
# فروع ومخازن الموبايل — Warehouse الخاصة بشركة المتجر الحالية.
# المخزون في ERPNext مربوط بالـ Warehouse، فدي هي مصدر الحقيقة.
company = frappe.db.get_single_value("Global Defaults", "default_company")
if not company:
    frappe.throw("الشركة غير محددة")

rows = frappe.db.sql("""
    SELECT
        w.name, w.warehouse_name, w.company, w.parent_warehouse,
        w.warehouse_type, w.disabled,
        COALESCE(SUM(b.actual_qty), 0) AS stock_qty,
        COUNT(DISTINCT b.item_code) AS product_count
    FROM `tabWarehouse` w
    LEFT JOIN `tabBin` b ON b.warehouse = w.name AND COALESCE(b.actual_qty, 0) != 0
    WHERE w.company = %s
      AND w.is_group = 0
    GROUP BY w.name, w.warehouse_name, w.company, w.parent_warehouse,
             w.warehouse_type, w.disabled, w.lft
    ORDER BY w.disabled ASC, w.lft ASC, w.name ASC
""", (company,), as_dict=True)

items = []
for r in rows:
    items.append({
        "id": r.get("name"),
        "name": r.get("name"),
        "warehouse_name": r.get("warehouse_name") or r.get("name"),
        "company": r.get("company"),
        "parent_warehouse": r.get("parent_warehouse"),
        "warehouse_type": r.get("warehouse_type"),
        "disabled": int(r.get("disabled") or 0),
        "stock_qty": float(r.get("stock_qty") or 0),
        "product_count": int(r.get("product_count") or 0),
    })

frappe.response["message"] = {"company": company, "items": items}
'''


SAVE_WAREHOUSE_SCRIPT = r'''
# إنشاء مخزن جديد في ERPNext من تطبيق الموبايل.
name = (frappe.form_dict.get("name") or "").strip()
if not name:
    frappe.throw("اسم المخزن مطلوب")

company = frappe.db.get_single_value("Global Defaults", "default_company")
if not company:
    frappe.throw("الشركة غير محددة")

existing = frappe.db.get_value(
    "Warehouse", {"company": company, "warehouse_name": name}, "name")
if existing:
    doc = frappe.get_doc("Warehouse", existing)
else:
    parent = frappe.db.get_value(
        "Warehouse", {"company": company, "is_group": 1, "parent_warehouse": ["is", "not set"]}, "name")
    if not parent:
        parent = frappe.db.get_value("Warehouse", {"company": company, "is_group": 1}, "name")
    doc = frappe.get_doc({
        "doctype": "Warehouse",
        "warehouse_name": name,
        "company": company,
        "parent_warehouse": parent,
        "is_group": 0,
        "disabled": 0,
    })
    doc.insert(ignore_permissions=True)

frappe.response["message"] = {
    "id": doc.name,
    "name": doc.name,
    "warehouse_name": doc.warehouse_name,
    "company": doc.company,
    "parent_warehouse": doc.parent_warehouse,
    "warehouse_type": doc.warehouse_type,
    "disabled": int(doc.disabled or 0),
    "stock_qty": 0,
    "product_count": 0,
}
'''


STOCK_TRANSFERS_SCRIPT = r'''
# تحويلات المخزون — Stock Entry / Material Transfer.
q = (frappe.form_dict.get("q") or "").strip()

company = frappe.db.get_single_value("Global Defaults", "default_company")
if not company:
    frappe.throw("الشركة غير محددة")

where = "se.company = %s AND se.stock_entry_type = 'Material Transfer'"
args = [company]
if q:
    like = "%" + q + "%"
    where = where + (
        " AND (se.name LIKE %s OR sed.item_name LIKE %s "
        "OR sed.s_warehouse LIKE %s OR sed.t_warehouse LIKE %s)"
    )
    args.extend([like, like, like, like])

rows = frappe.db.sql(
    "SELECT se.name, se.docstatus, se.posting_date, se.creation, "
    "sed.item_code, sed.item_name, sed.qty, sed.s_warehouse, sed.t_warehouse "
    "FROM `tabStock Entry` se "
    "JOIN `tabStock Entry Detail` sed ON sed.parent = se.name "
    "WHERE " + where + " "
    "ORDER BY se.posting_date DESC, se.creation DESC LIMIT 100",
    tuple(args),
    as_dict=True,
)

items = []
for r in rows:
    status = "Draft"
    if frappe.utils.cint(r.get("docstatus") or 0) == 1:
        status = "Submitted"
    elif frappe.utils.cint(r.get("docstatus") or 0) == 2:
        status = "Cancelled"
    items.append({
        "name": r.get("name"),
        "status": status,
        "posting_date": str(r.get("posting_date") or ""),
        "item_code": r.get("item_code"),
        "item_name": r.get("item_name") or r.get("item_code"),
        "qty": float(r.get("qty") or 0),
        "from_warehouse": r.get("s_warehouse"),
        "to_warehouse": r.get("t_warehouse"),
    })

warehouse_rows = frappe.db.sql(
    "SELECT name, warehouse_name FROM `tabWarehouse` "
    "WHERE company = %s AND is_group = 0 AND disabled = 0 "
    "ORDER BY lft ASC, name ASC",
    (company,),
    as_dict=True,
)
warehouses = []
for w in warehouse_rows:
    warehouses.append({
        "id": w.get("name"),
        "name": w.get("warehouse_name") or w.get("name"),
    })

product_rows = frappe.db.sql(
    "SELECT i.item_code, i.item_name, i.stock_uom, COALESCE(SUM(b.actual_qty), 0) AS stock_qty "
    "FROM `tabItem` i "
    "LEFT JOIN `tabBin` b ON b.item_code = i.item_code "
    "WHERE i.disabled = 0 AND i.is_stock_item = 1 "
    "GROUP BY i.item_code, i.item_name, i.stock_uom "
    "ORDER BY i.item_name ASC LIMIT 200",
    as_dict=True,
)
products = []
for p in product_rows:
    products.append({
        "code": p.get("item_code"),
        "name": p.get("item_name") or p.get("item_code"),
        "uom": p.get("stock_uom"),
        "stock_qty": float(p.get("stock_qty") or 0),
    })

frappe.response["message"] = {
    "items": items,
    "warehouses": warehouses,
    "products": products,
}
'''


SAVE_STOCK_TRANSFER_SCRIPT = r'''
# إنشاء تحويل مخزون في ERPNext بنفس مستند Stock Entry القياسي.
item_code = (frappe.form_dict.get("item_code") or "").strip()
from_warehouse = (frappe.form_dict.get("from_warehouse") or "").strip()
to_warehouse = (frappe.form_dict.get("to_warehouse") or "").strip()
qty = frappe.utils.flt(frappe.form_dict.get("qty") or 0)
notes = (frappe.form_dict.get("notes") or "").strip()

if not item_code:
    frappe.throw("المنتج مطلوب")
if not from_warehouse or not to_warehouse:
    frappe.throw("مخزن التحويل والاستلام مطلوبان")
if from_warehouse == to_warehouse:
    frappe.throw("لا يمكن التحويل لنفس المخزن")
if qty <= 0:
    frappe.throw("الكمية غير صحيحة")

company = frappe.db.get_single_value("Global Defaults", "default_company")
if not company:
    frappe.throw("الشركة غير محددة")
if not frappe.db.exists("Item", item_code):
    frappe.throw("المنتج غير موجود")
if not frappe.db.exists("Warehouse", {"name": from_warehouse, "company": company, "is_group": 0}):
    frappe.throw("مخزن التحويل غير موجود")
if not frappe.db.exists("Warehouse", {"name": to_warehouse, "company": company, "is_group": 0}):
    frappe.throw("مخزن الاستلام غير موجود")

item = frappe.get_doc("Item", item_code)
available = frappe.db.get_value(
    "Bin", {"item_code": item_code, "warehouse": from_warehouse}, "actual_qty")
if float(available or 0) < qty:
    frappe.throw("الكمية المتاحة في مخزن التحويل غير كافية")

doc = frappe.get_doc({
    "doctype": "Stock Entry",
    "company": company,
    "stock_entry_type": "Material Transfer",
    "purpose": "Material Transfer",
    "posting_date": frappe.utils.nowdate(),
    "remarks": notes,
    "items": [{
        "item_code": item_code,
        "item_name": item.item_name,
        "qty": qty,
        "uom": item.stock_uom,
        "stock_uom": item.stock_uom,
        "s_warehouse": from_warehouse,
        "t_warehouse": to_warehouse,
        "conversion_factor": 1,
    }],
})
doc.insert(ignore_permissions=True)
doc.submit()

fresh = frappe.get_doc("Stock Entry", doc.name)
line = fresh.items[0]
frappe.response["message"] = {
    "name": fresh.name,
    "status": "Submitted",
    "posting_date": str(fresh.posting_date or ""),
    "item_code": line.item_code,
    "item_name": line.item_name or line.item_code,
    "qty": float(line.qty or 0),
    "from_warehouse": line.s_warehouse,
    "to_warehouse": line.t_warehouse,
}
'''


COUPONS_SCRIPT = r'''
# كوبونات الموبايل — مبنية على ERPNext Coupon Code + Pricing Rule.
company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

rows = frappe.db.sql("""
    SELECT
        c.name, c.coupon_code, c.pricing_rule, c.valid_from, c.valid_upto,
        c.maximum_use, c.used,
        pr.disable, pr.rate_or_discount, pr.discount_percentage,
        pr.discount_amount, pr.min_amt, pr.max_amt, pr.currency
    FROM `tabCoupon Code` c
    LEFT JOIN `tabPricing Rule` pr ON pr.name = c.pricing_rule
    ORDER BY c.modified DESC
    LIMIT 200
""", as_dict=True)

items = []
for r in rows:
    fixed = r.get("rate_or_discount") == "Discount Amount"
    value = r.get("discount_amount") if fixed else r.get("discount_percentage")
    min_order = float(r.get("min_amt") or 0)
    max_order = float(r.get("max_amt") or 0)
    usage_limit = frappe.utils.cint(r.get("maximum_use") or 0)
    items.append({
        "id": r.get("name"),
        "name": r.get("name"),
        "code": r.get("coupon_code"),
        "coupon_code": r.get("coupon_code"),
        "type": "fixed" if fixed else "percentage",
        "value": float(value or 0),
        "is_active": 0 if frappe.utils.cint(r.get("disable") or 0) else 1,
        "used_count": frappe.utils.cint(r.get("used") or 0),
        "used": frappe.utils.cint(r.get("used") or 0),
        "pricing_rule": r.get("pricing_rule"),
        "min_order_amount": min_order or None,
        "max_discount": max_order or None,
        "usage_limit": usage_limit or None,
        "starts_at": str(r.get("valid_from") or ""),
        "expires_at": str(r.get("valid_upto") or ""),
        "currency": r.get("currency") or currency,
    })

frappe.response["message"] = {"currency": currency, "items": items}
'''


SAVE_COUPON_SCRIPT = r'''
# إنشاء Coupon Code + Pricing Rule بنفس آلية ERPNext الأصلية.
code = (frappe.form_dict.get("code") or "").strip().upper()
kind = (frappe.form_dict.get("type") or "percentage").strip()
value = frappe.utils.flt(frappe.form_dict.get("value"))
is_active = frappe.utils.cint(frappe.form_dict.get("is_active"))
min_order = frappe.utils.flt(frappe.form_dict.get("min_order_amount"))
max_order = frappe.utils.flt(frappe.form_dict.get("max_discount"))
usage_limit = frappe.utils.cint(frappe.form_dict.get("usage_limit"))
starts_at = (frappe.form_dict.get("starts_at") or "").strip()
expires_at = (frappe.form_dict.get("expires_at") or "").strip()

if not code:
    frappe.throw("كود الخصم مطلوب")
if value <= 0:
    frappe.throw("قيمة الخصم مطلوبة")
if kind not in ["percentage", "fixed"]:
    frappe.throw("نوع الخصم غير صالح")
if kind == "percentage" and value > 100:
    frappe.throw("نسبة الخصم لا يمكن أن تتجاوز 100%")
if frappe.db.exists("Coupon Code", {"coupon_code": code}):
    frappe.throw("كود الخصم مستخدم بالفعل")

company = frappe.db.get_single_value("Global Defaults", "default_company")
if not company:
    frappe.throw("الشركة غير محددة")
currency = frappe.db.get_value("Company", company, "default_currency") or frappe.db.get_default("currency") or "EGP"
price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name") or "Standard Selling"

rule_data = {
    "doctype": "Pricing Rule",
    "title": "Coupon " + code,
    "disable": 0 if is_active else 1,
    "apply_on": "Transaction",
    "price_or_product_discount": "Price",
    "coupon_code_based": 1,
    "selling": 1,
    "buying": 0,
    "company": company,
    "currency": currency,
    "for_price_list": price_list,
    "rate_or_discount": "Discount Amount" if kind == "fixed" else "Discount Percentage",
    "apply_discount_on": "Grand Total",
}
if min_order > 0:
    rule_data["min_amt"] = min_order
if max_order > 0:
    rule_data["max_amt"] = max_order
if starts_at:
    rule_data["valid_from"] = starts_at
if expires_at:
    rule_data["valid_upto"] = expires_at
if kind == "fixed":
    rule_data["discount_amount"] = value
else:
    rule_data["discount_percentage"] = value

rule = frappe.get_doc(rule_data)
rule.insert(ignore_permissions=True)

coupon_data = {
    "doctype": "Coupon Code",
    "coupon_name": code,
    "coupon_type": "Promotional",
    "coupon_code": code,
    "pricing_rule": rule.name,
}
if usage_limit > 0:
    coupon_data["maximum_use"] = usage_limit
if starts_at:
    coupon_data["valid_from"] = starts_at
if expires_at:
    coupon_data["valid_upto"] = expires_at

coupon = frappe.get_doc(coupon_data)
coupon.insert(ignore_permissions=True)
frappe.db.commit()

frappe.response["message"] = {
    "id": coupon.name,
    "name": coupon.name,
    "code": coupon.coupon_code,
    "coupon_code": coupon.coupon_code,
    "type": kind,
    "value": float(value or 0),
    "is_active": 1 if is_active else 0,
    "used_count": 0,
    "used": 0,
    "pricing_rule": rule.name,
    "min_order_amount": min_order or None,
    "max_discount": max_order or None,
    "usage_limit": usage_limit or None,
    "starts_at": starts_at,
    "expires_at": expires_at,
    "currency": currency,
}
'''


COUPON_STATUS_SCRIPT = r'''
# تفعيل/تعطيل كوبون من الموبايل عن طريق Pricing Rule.disable.
coupon_id = (frappe.form_dict.get("id") or "").strip()
active = frappe.utils.cint(frappe.form_dict.get("active"))
if not coupon_id:
    frappe.throw("الكوبون مطلوب")
if not frappe.db.exists("Coupon Code", coupon_id):
    frappe.throw("الكوبون غير موجود")

coupon = frappe.get_doc("Coupon Code", coupon_id)
if not coupon.pricing_rule or not frappe.db.exists("Pricing Rule", coupon.pricing_rule):
    frappe.throw("قاعدة الخصم غير موجودة")

frappe.db.set_value("Pricing Rule", coupon.pricing_rule, "disable", 0 if active else 1)
rule = frappe.get_doc("Pricing Rule", coupon.pricing_rule)
fixed = rule.rate_or_discount == "Discount Amount"
value = rule.discount_amount if fixed else rule.discount_percentage
currency = rule.currency or frappe.db.get_default("currency") or "EGP"

frappe.response["message"] = {
    "id": coupon.name,
    "name": coupon.name,
    "code": coupon.coupon_code,
    "coupon_code": coupon.coupon_code,
    "type": "fixed" if fixed else "percentage",
    "value": float(value or 0),
    "is_active": 1 if active else 0,
    "used_count": frappe.utils.cint(coupon.used or 0),
    "used": frappe.utils.cint(coupon.used or 0),
    "pricing_rule": rule.name,
    "min_order_amount": float(rule.min_amt or 0) or None,
    "max_discount": float(rule.max_amt or 0) or None,
    "usage_limit": frappe.utils.cint(coupon.maximum_use or 0) or None,
    "starts_at": str(coupon.valid_from or ""),
    "expires_at": str(coupon.valid_upto or ""),
    "currency": currency,
}
'''


DELETE_COUPON_SCRIPT = r'''
# حذف Coupon Code وقاعدة Pricing Rule المرتبطة به كوحدة واحدة.
coupon_id = (frappe.form_dict.get("id") or "").strip()
if not coupon_id:
    frappe.throw("الكوبون مطلوب")
if not frappe.db.exists("Coupon Code", coupon_id):
    frappe.response["message"] = {"ok": 1, "deleted": 1}
else:
    coupon = frappe.get_doc("Coupon Code", coupon_id)
    if frappe.utils.cint(coupon.used or 0) > 0:
        frappe.throw("لا يمكن حذف كوبون تم استخدامه. يمكنك تعطيله بدلاً من ذلك")

    pricing_rule = coupon.pricing_rule
    frappe.delete_doc("Coupon Code", coupon_id, ignore_permissions=True)
    if pricing_rule and frappe.db.exists("Pricing Rule", pricing_rule):
        frappe.delete_doc("Pricing Rule", pricing_rule, ignore_permissions=True)
    frappe.db.commit()
    frappe.response["message"] = {"ok": 1, "deleted": 1}
'''


CUSTOMERS_SCRIPT = r'''
# عملاء الموبايل — Customer + إحصائيات من Sales Order.
search = (frappe.form_dict.get("search") or "").strip()

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

conds = "1=1"
args = []
if search:
    conds = conds + " AND (c.name LIKE %s OR c.customer_name LIKE %s OR c.email_id LIKE %s OR c.mobile_no LIKE %s)"
    like = "%" + search + "%"
    args.append(like)
    args.append(like)
    args.append(like)
    args.append(like)

rows = frappe.db.sql("""
    SELECT
        c.name, c.customer_name, c.customer_group, c.territory,
        c.mobile_no, c.email_id,
        COUNT(so.name) AS order_count,
        COALESCE(SUM(CASE WHEN so.docstatus = 1 THEN so.grand_total ELSE 0 END), 0) AS total_spent,
        MAX(CASE WHEN so.docstatus = 1 THEN so.transaction_date ELSE NULL END) AS last_order_date
    FROM `tabCustomer` c
    LEFT JOIN `tabSales Order` so ON so.customer = c.name
    WHERE """ + conds + """
    GROUP BY c.name, c.customer_name, c.customer_group, c.territory, c.mobile_no, c.email_id
    ORDER BY c.modified DESC
    LIMIT 200
""", tuple(args), as_dict=True)

items = []
for r in rows:
    items.append({
        "id": r.get("name"),
        "name": r.get("name"),
        "customer_name": r.get("customer_name") or r.get("name"),
        "customer_group": r.get("customer_group"),
        "territory": r.get("territory"),
        "phone": r.get("mobile_no"),
        "mobile_no": r.get("mobile_no"),
        "email": r.get("email_id"),
        "email_id": r.get("email_id"),
        "order_count": frappe.utils.cint(r.get("order_count") or 0),
        "total_spent": float(r.get("total_spent") or 0),
        "last_order_date": str(r.get("last_order_date") or ""),
        "currency": currency,
    })

frappe.response["message"] = {"currency": currency, "items": items}
'''


CUSTOMER_DETAIL_SCRIPT = r'''
# تفاصيل عميل واحد مع آخر طلباته من Sales Order.
customer_id = (frappe.form_dict.get("id") or "").strip()
if not customer_id:
    frappe.throw("العميل مطلوب")
if not frappe.db.exists("Customer", customer_id):
    frappe.throw("العميل غير موجود")

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

customer = frappe.db.get_value(
    "Customer",
    customer_id,
    ["name", "customer_name", "customer_group", "territory", "mobile_no", "email_id"],
    as_dict=True,
) or {}

stats = frappe.db.sql(
    "SELECT COUNT(name) AS order_count, "
    "COALESCE(SUM(CASE WHEN docstatus = 1 THEN grand_total ELSE 0 END), 0) AS total_spent, "
    "MAX(CASE WHEN docstatus = 1 THEN transaction_date ELSE NULL END) AS last_order_date "
    "FROM `tabSales Order` WHERE customer = %s",
    (customer_id,),
    as_dict=True,
)
summary = stats[0] if stats else {}

rows = frappe.db.sql(
    "SELECT name, status, transaction_date, grand_total, total_qty, currency "
    "FROM `tabSales Order` WHERE customer = %s "
    "ORDER BY transaction_date DESC, creation DESC LIMIT 50",
    (customer_id,),
    as_dict=True,
)
orders = []
for row in rows:
    orders.append({
        "name": row.get("name"),
        "status": row.get("status"),
        "date": str(row.get("transaction_date") or ""),
        "total": float(row.get("grand_total") or 0),
        "item_count": float(row.get("total_qty") or 0),
        "currency": row.get("currency") or currency,
    })

frappe.response["message"] = {
    "customer": {
        "id": customer.get("name"),
        "name": customer.get("name"),
        "customer_name": customer.get("customer_name") or customer.get("name"),
        "customer_group": customer.get("customer_group"),
        "territory": customer.get("territory"),
        "phone": customer.get("mobile_no"),
        "mobile_no": customer.get("mobile_no"),
        "email": customer.get("email_id"),
        "email_id": customer.get("email_id"),
        "order_count": frappe.utils.cint(summary.get("order_count") or 0),
        "total_spent": float(summary.get("total_spent") or 0),
        "last_order_date": str(summary.get("last_order_date") or ""),
        "currency": currency,
    },
    "orders": orders,
}
'''


SAVE_CUSTOMER_SCRIPT = r'''
# إنشاء عميل ERPNext من تطبيق الموبايل.
name = (frappe.form_dict.get("name") or "").strip()
email = (frappe.form_dict.get("email") or "").strip()
phone = (frappe.form_dict.get("phone") or "").strip()

if not name:
    frappe.throw("اسم العميل مطلوب")
if email and frappe.db.exists("Customer", {"email_id": email}):
    frappe.throw("يوجد عميل بنفس البريد الإلكتروني")
if phone and frappe.db.exists("Customer", {"mobile_no": phone}):
    frappe.throw("يوجد عميل بنفس رقم الجوال")

group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

doc = frappe.get_doc({
    "doctype": "Customer",
    "customer_name": name,
    "customer_type": "Individual",
    "customer_group": group,
    "territory": territory,
    "mobile_no": phone,
    "email_id": email,
})
doc.insert(ignore_permissions=True)
frappe.db.commit()

frappe.response["message"] = {
    "id": doc.name,
    "name": doc.name,
    "customer_name": doc.customer_name,
    "customer_group": doc.customer_group,
    "territory": doc.territory,
    "phone": doc.mobile_no,
    "mobile_no": doc.mobile_no,
    "email": doc.email_id,
    "email_id": doc.email_id,
    "order_count": 0,
    "total_spent": 0,
    "last_order_date": "",
    "currency": currency,
}
'''


DELETE_PRODUCT_SCRIPT = r'''
# حذف منتج من تطبيق الموبايل. لو ERPNext منع الحذف بسبب معاملات مرتبطة،
# نخفي المنتج بدلاً من كسر تجربة التاجر.
item_id = (frappe.form_dict.get("id") or "").strip()
if not item_id:
    frappe.throw("المنتج مطلوب")
if not frappe.db.exists("Item", item_id):
    frappe.response["message"] = {"ok": 1, "deleted": 1}
else:
    try:
        frappe.delete_doc("Item", item_id, ignore_permissions=True)
        frappe.response["message"] = {"ok": 1, "deleted": 1}
    except Exception:
        frappe.db.set_value("Item", item_id, "disabled", 1)
        frappe.response["message"] = {"ok": 1, "deleted": 0, "disabled": 1}
'''


ORDERS_LIST_SCRIPT = r'''
# قائمة طلبات الموبايل — Sales Orders بفلتر حالة/تاريخ.
# ⚠️ safe_exec: مفيش import، مفيش أسماء بـ _، مفيش فك تغليف، مفيش .format().

page = frappe.utils.cint(frappe.form_dict.get("page") or 1)
if page < 1:
    page = 1
size = 20
start = (page - 1) * size

status = (frappe.form_dict.get("status") or "").strip()
dfrom = (frappe.form_dict.get("from") or "").strip()
dto = (frappe.form_dict.get("to") or "").strip()

# فلتر الحالة كـ token مجموعة → قائمة حالات ERPNext.
status_map = {
    "draft": ["Draft"],
    "pending": ["To Deliver and Bill", "To Deliver", "To Bill"],
    "completed": ["Completed"],
    "onhold": ["On Hold"],
    "closed": ["Closed"],
    "cancelled": ["Cancelled"],
}

conds = "1=1"
args = []
if status in status_map:
    placeholders = ", ".join(["%s"] * len(status_map[status]))
    conds = conds + " AND so.status IN (" + placeholders + ")"
    for s in status_map[status]:
        args.append(s)
if dfrom:
    conds = conds + " AND so.transaction_date >= %s"
    args.append(dfrom)
if dto:
    conds = conds + " AND so.transaction_date <= %s"
    args.append(dto)

list_sql = (
    "SELECT so.name, so.status, so.customer, so.customer_name, "
    "so.grand_total, so.total_qty, so.transaction_date "
    "FROM `tabSales Order` so WHERE " + conds + " "
    "ORDER BY so.transaction_date DESC, so.creation DESC LIMIT %s OFFSET %s"
)
rows = frappe.db.sql(list_sql, tuple(args) + (size, start), as_dict=True)

count_sql = "SELECT COUNT(*) FROM `tabSales Order` so WHERE " + conds
total_row = frappe.db.sql(count_sql, tuple(args))
total = int(total_row[0][0] or 0) if total_row else 0

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

items = []
for r in rows:
    items.append({
        "name": r.get("name"),
        "status": r.get("status"),
        "customer": r.get("customer"),
        "customer_name": r.get("customer_name"),
        "total": float(r.get("grand_total") or 0),
        "item_count": float(r.get("total_qty") or 0),
        "transaction_date": str(r.get("transaction_date") or ""),
    })

frappe.response["message"] = {
    "currency": currency,
    "items": items,
    "pagination": {
        "page": page,
        "size": size,
        "total": total,
        "has_more": (start + len(items)) < total,
    },
}
'''


ORDER_DETAIL_SCRIPT = r'''
# تفاصيل طلب موبايل — Sales Order واحد بأصنافه.
# ⚠️ safe_exec: مفيش import، مفيش أسماء بـ _، مفيش فك تغليف، مفيش .format().

name = (frappe.form_dict.get("name") or "").strip()
if not name:
    frappe.throw("رقم الطلب مطلوب")

doc = frappe.get_doc("Sales Order", name)
company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or doc.currency or frappe.db.get_default("currency") or "EGP"

lines = []
for it in doc.items:
    lines.append({
        "item_code": it.item_code,
        "name": it.item_name,
        "qty": float(it.qty or 0),
        "rate": float(it.rate or 0),
        "amount": float(it.amount or 0),
    })

frappe.response["message"] = {
    "name": doc.name,
    "status": doc.status,
    "customer": doc.customer,
    "customer_name": doc.customer_name,
    "customer_phone": doc.get("contact_mobile") or doc.get("contact_phone"),
    "customer_email": doc.get("contact_email"),
    "shipping_address": doc.get("shipping_address") or doc.get("address_display"),
    "transaction_date": str(doc.transaction_date or ""),
    "currency": currency,
    "items": lines,
    "item_count": float(doc.total_qty or 0),
    "subtotal": float(doc.net_total or doc.total or 0),
    "shipping": 0,
    "discount": float(doc.discount_amount or 0),
    "tax": float(doc.total_taxes_and_charges or 0),
    "total": float(doc.grand_total or 0),
    "notes": doc.get("terms") or "",
}
'''


CREATE_ORDER_SCRIPT = r'''
# إنشاء طلب يدوي من تطبيق الموبايل — للطلبات اللي جاية خارج المتجر.
# ⚠️ safe_exec: مفيش import، مفيش أسماء بـ _، مفيش فك تغليف، مفيش .format().

customer_name = (frappe.form_dict.get("customer_name") or "").strip()
phone = (frappe.form_dict.get("customer_phone") or "").strip()
email = (frappe.form_dict.get("customer_email") or "").strip()
address = (frappe.form_dict.get("shipping_address") or "").strip()
item_code = (frappe.form_dict.get("item_code") or "").strip()
qty = frappe.utils.flt(frappe.form_dict.get("qty") or 1)
notes = (frappe.form_dict.get("notes") or "").strip()

if not customer_name:
    frappe.throw("اسم العميل مطلوب")
if not item_code:
    frappe.throw("المنتج مطلوب")
if qty <= 0:
    frappe.throw("الكمية يجب أن تكون أكبر من صفر")
if not frappe.db.exists("Item", item_code):
    frappe.throw("المنتج غير موجود")

customer = frappe.db.get_value("Customer", {"customer_name": customer_name})
if not customer:
    group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
    territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
    cust = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": customer_name,
        "customer_type": "Individual",
        "customer_group": group,
        "territory": territory,
        "mobile_no": phone,
        "email_id": email,
    })
    cust.insert(ignore_permissions=True)
    customer = cust.name
else:
    values = {}
    if phone:
        values["mobile_no"] = phone
    if email:
        values["email_id"] = email
    if values:
        frappe.db.set_value("Customer", customer, values)

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"
warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")
rate = frappe.db.get_value(
    "Item Price",
    {"item_code": item_code, "selling": 1},
    "price_list_rate",
) or frappe.db.get_value("Item", item_code, "standard_rate") or 0

row = {
    "item_code": item_code,
    "qty": qty,
    "rate": rate,
}
if warehouse:
    row["warehouse"] = warehouse

doc = frappe.get_doc({
    "doctype": "Sales Order",
    "customer": customer,
    "company": company,
    "currency": currency,
    "transaction_date": frappe.utils.nowdate(),
    "delivery_date": frappe.utils.add_days(frappe.utils.nowdate(), 3),
    "items": [row],
})
if notes:
    doc.terms = notes

doc.insert(ignore_permissions=True)
doc.submit()
if address:
    doc.add_comment("Comment", "بيانات طلب خارجي\nالعنوان: " + address)
frappe.db.commit()

fresh = frappe.get_doc("Sales Order", doc.name)
lines = []
for it in fresh.items:
    lines.append({
        "item_code": it.item_code,
        "name": it.item_name,
        "qty": float(it.qty or 0),
        "rate": float(it.rate or 0),
        "amount": float(it.amount or 0),
    })

frappe.response["message"] = {
    "name": fresh.name,
    "status": fresh.status,
    "customer": fresh.customer,
    "customer_name": fresh.customer_name,
    "customer_phone": fresh.get("contact_mobile") or fresh.get("contact_phone"),
    "customer_email": fresh.get("contact_email"),
    "shipping_address": fresh.get("shipping_address") or fresh.get("address_display"),
    "transaction_date": str(fresh.transaction_date or ""),
    "currency": currency,
    "items": lines,
    "item_count": float(fresh.total_qty or 0),
    "subtotal": float(fresh.net_total or fresh.total or 0),
    "shipping": 0,
    "discount": float(fresh.discount_amount or 0),
    "tax": float(fresh.total_taxes_and_charges or 0),
    "total": float(fresh.grand_total or 0),
    "notes": fresh.get("terms") or "",
}
'''


ORDER_STATUS_SCRIPT = r'''
# تغيير حالة طلب — تحولات Sales Order أصلية.
# ⚠️ safe_exec: مفيش import، مفيش أسماء بـ _، مفيش فك تغليف، مفيش .format().

name = (frappe.form_dict.get("name") or "").strip()
action = (frappe.form_dict.get("action") or "").strip()
if not name:
    frappe.throw("رقم الطلب مطلوب")

doc = frappe.get_doc("Sales Order", name)

if action == "submit":
    doc.submit()
elif action == "cancel":
    doc.cancel()
elif action == "hold":
    doc.update_status("On Hold")
elif action == "close":
    doc.update_status("Closed")
elif action == "resume" or action == "reopen":
    doc.update_status("Draft")
else:
    frappe.throw("إجراء غير معروف")

frappe.db.commit()
fresh = frappe.get_doc("Sales Order", name)
company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or fresh.currency or frappe.db.get_default("currency") or "EGP"

lines = []
for it in fresh.items:
    lines.append({
        "item_code": it.item_code,
        "name": it.item_name,
        "qty": float(it.qty or 0),
        "rate": float(it.rate or 0),
        "amount": float(it.amount or 0),
    })

frappe.response["message"] = {
    "name": fresh.name,
    "status": fresh.status,
    "customer": fresh.customer,
    "customer_name": fresh.customer_name,
    "customer_phone": fresh.get("contact_mobile") or fresh.get("contact_phone"),
    "customer_email": fresh.get("contact_email"),
    "shipping_address": fresh.get("shipping_address") or fresh.get("address_display"),
    "transaction_date": str(fresh.transaction_date or ""),
    "currency": currency,
    "items": lines,
    "item_count": float(fresh.total_qty or 0),
    "subtotal": float(fresh.net_total or fresh.total or 0),
    "shipping": 0,
    "discount": float(fresh.discount_amount or 0),
    "tax": float(fresh.total_taxes_and_charges or 0),
    "total": float(fresh.grand_total or 0),
    "notes": fresh.get("terms") or "",
}
'''


INVOICES_LIST_SCRIPT = r'''
# قائمة فواتير الموبايل — Sales Invoice بفلتر حالة/تاريخ.
page = frappe.utils.cint(frappe.form_dict.get("page") or 1)
if page < 1:
    page = 1
size = 20
start = (page - 1) * size

status = (frappe.form_dict.get("status") or "").strip()
dfrom = (frappe.form_dict.get("from") or "").strip()
dto = (frappe.form_dict.get("to") or "").strip()

status_map = {
    "draft": ["Draft"],
    "paid": ["Paid"],
    "unpaid": ["Unpaid", "Partly Paid"],
    "overdue": ["Overdue"],
    "cancelled": ["Cancelled"],
}

conds = "1=1"
args = []
if status in status_map:
    placeholders = ", ".join(["%s"] * len(status_map[status]))
    conds = conds + " AND si.status IN (" + placeholders + ")"
    for s in status_map[status]:
        args.append(s)
if dfrom:
    conds = conds + " AND si.posting_date >= %s"
    args.append(dfrom)
if dto:
    conds = conds + " AND si.posting_date <= %s"
    args.append(dto)

list_sql = (
    "SELECT si.name, si.status, si.customer, si.customer_name, "
    "si.grand_total, si.outstanding_amount, si.total_qty, si.posting_date, si.currency "
    "FROM `tabSales Invoice` si WHERE " + conds + " "
    "ORDER BY si.posting_date DESC, si.creation DESC LIMIT %s OFFSET %s"
)
rows = frappe.db.sql(list_sql, tuple(args) + (size, start), as_dict=True)

count_sql = "SELECT COUNT(*) FROM `tabSales Invoice` si WHERE " + conds
total_row = frappe.db.sql(count_sql, tuple(args))
total = int(total_row[0][0] or 0) if total_row else 0

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

items = []
for r in rows:
    items.append({
        "name": r.get("name"),
        "status": r.get("status"),
        "customer": r.get("customer"),
        "customer_name": r.get("customer_name"),
        "total": float(r.get("grand_total") or 0),
        "outstanding": float(r.get("outstanding_amount") or 0),
        "item_count": float(r.get("total_qty") or 0),
        "posting_date": str(r.get("posting_date") or ""),
        "currency": r.get("currency") or currency,
    })

frappe.response["message"] = {
    "currency": currency,
    "items": items,
    "pagination": {
        "page": page,
        "size": size,
        "total": total,
        "has_more": (start + len(items)) < total,
    },
}
'''


INVOICE_DETAIL_SCRIPT = r'''
# تفاصيل فاتورة موبايل — Sales Invoice واحد بأصنافه.
name = (frappe.form_dict.get("name") or "").strip()
if not name:
    frappe.throw("رقم الفاتورة مطلوب")
if not frappe.db.exists("Sales Invoice", name):
    frappe.throw("الفاتورة غير موجودة")

doc = frappe.get_doc("Sales Invoice", name)
company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or doc.currency or frappe.db.get_default("currency") or "EGP"

lines = []
for it in doc.items:
    lines.append({
        "item_code": it.item_code,
        "name": it.item_name,
        "qty": float(it.qty or 0),
        "rate": float(it.rate or 0),
        "amount": float(it.amount or 0),
    })

frappe.response["message"] = {
    "name": doc.name,
    "status": doc.status,
    "customer": doc.customer,
    "customer_name": doc.customer_name,
    "customer_phone": doc.get("contact_mobile") or doc.get("contact_phone"),
    "customer_email": doc.get("contact_email"),
    "posting_date": str(doc.posting_date or ""),
    "currency": currency,
    "items": lines,
    "item_count": float(doc.total_qty or 0),
    "subtotal": float(doc.net_total or doc.total or 0),
    "discount": float(doc.discount_amount or 0),
    "tax": float(doc.total_taxes_and_charges or 0),
    "total": float(doc.grand_total or 0),
    "outstanding": float(doc.outstanding_amount or 0),
    "notes": doc.get("terms") or "",
}
'''


RETURNS_LIST_SCRIPT = r'''
# قائمة المرتجعات — Sales Invoice التي عليها is_return=1.
page = frappe.utils.cint(frappe.form_dict.get("page") or 1)
if page < 1:
    page = 1
size = 20
start = (page - 1) * size

status = (frappe.form_dict.get("status") or "").strip()
dfrom = (frappe.form_dict.get("from") or "").strip()
dto = (frappe.form_dict.get("to") or "").strip()

conds = "si.is_return = 1"
args = []
if status == "draft":
    conds = conds + " AND si.docstatus = 0"
elif status == "submitted":
    conds = conds + " AND si.docstatus = 1"
elif status == "cancelled":
    conds = conds + " AND si.docstatus = 2"
if dfrom:
    conds = conds + " AND si.posting_date >= %s"
    args.append(dfrom)
if dto:
    conds = conds + " AND si.posting_date <= %s"
    args.append(dto)

list_sql = (
    "SELECT si.name, si.status, si.customer, si.customer_name, "
    "si.grand_total, si.outstanding_amount, si.total_qty, si.posting_date, "
    "si.currency, si.return_against "
    "FROM `tabSales Invoice` si WHERE " + conds + " "
    "ORDER BY si.posting_date DESC, si.creation DESC LIMIT %s OFFSET %s"
)
rows = frappe.db.sql(list_sql, tuple(args) + (size, start), as_dict=True)

count_sql = "SELECT COUNT(*) FROM `tabSales Invoice` si WHERE " + conds
total_row = frappe.db.sql(count_sql, tuple(args))
total = int(total_row[0][0] or 0) if total_row else 0

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

items = []
for r in rows:
    total_value = float(r.get("grand_total") or 0)
    outstanding_value = float(r.get("outstanding_amount") or 0)
    items.append({
        "name": r.get("name"),
        "status": r.get("status"),
        "customer": r.get("customer"),
        "customer_name": r.get("customer_name"),
        "total": abs(total_value),
        "outstanding": abs(outstanding_value),
        "item_count": abs(float(r.get("total_qty") or 0)),
        "posting_date": str(r.get("posting_date") or ""),
        "currency": r.get("currency") or currency,
        "return_against": r.get("return_against"),
    })

frappe.response["message"] = {
    "currency": currency,
    "items": items,
    "pagination": {
        "page": page,
        "size": size,
        "total": total,
        "has_more": (start + len(items)) < total,
    },
}
'''


RETURN_DETAIL_SCRIPT = r'''
# تفاصيل مرتجع — Sales Invoice is_return=1.
name = (frappe.form_dict.get("name") or "").strip()
if not name:
    frappe.throw("رقم المرتجع مطلوب")
if not frappe.db.exists("Sales Invoice", name):
    frappe.throw("المرتجع غير موجود")

doc = frappe.get_doc("Sales Invoice", name)
if not frappe.utils.cint(doc.get("is_return") or 0):
    frappe.throw("هذه الفاتورة ليست مرتجع")

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or doc.currency or frappe.db.get_default("currency") or "EGP"

lines = []
for it in doc.items:
    lines.append({
        "item_code": it.item_code,
        "name": it.item_name,
        "qty": abs(float(it.qty or 0)),
        "rate": abs(float(it.rate or 0)),
        "amount": abs(float(it.amount or 0)),
    })

frappe.response["message"] = {
    "name": doc.name,
    "status": doc.status,
    "customer": doc.customer,
    "customer_name": doc.customer_name,
    "customer_phone": doc.get("contact_mobile") or doc.get("contact_phone"),
    "customer_email": doc.get("contact_email"),
    "posting_date": str(doc.posting_date or ""),
    "currency": currency,
    "items": lines,
    "item_count": abs(float(doc.total_qty or 0)),
    "subtotal": abs(float(doc.net_total or doc.total or 0)),
    "discount": abs(float(doc.discount_amount or 0)),
    "tax": abs(float(doc.total_taxes_and_charges or 0)),
    "total": abs(float(doc.grand_total or 0)),
    "outstanding": abs(float(doc.outstanding_amount or 0)),
    "return_against": doc.get("return_against"),
    "notes": doc.get("terms") or "",
}
'''


ACCOUNT_STATEMENT_SCRIPT = r'''
# كشف حساب التاجر — ملخص وحركات من Sales Invoice وPayment Entry.
dfrom = (frappe.form_dict.get("from") or "").strip()
dto = (frappe.form_dict.get("to") or "").strip()

company = frappe.db.get_single_value("Global Defaults", "default_company")
currency = frappe.db.get_value("Company", company, "default_currency") if company else None
currency = currency or frappe.db.get_default("currency") or "EGP"

date_cond = ""
args = []
if dfrom:
    date_cond = date_cond + " AND posting_date >= %s"
    args.append(dfrom)
if dto:
    date_cond = date_cond + " AND posting_date <= %s"
    args.append(dto)

sales_row = frappe.db.sql(
    "SELECT COALESCE(SUM(grand_total), 0), COALESCE(SUM(outstanding_amount), 0) "
    "FROM `tabSales Invoice` "
    "WHERE docstatus = 1 AND IFNULL(is_return, 0) = 0" + date_cond,
    tuple(args),
)
sales_total = float(sales_row[0][0] or 0) if sales_row else 0
outstanding_total = float(sales_row[0][1] or 0) if sales_row else 0

returns_row = frappe.db.sql(
    "SELECT COALESCE(SUM(ABS(grand_total)), 0) FROM `tabSales Invoice` "
    "WHERE docstatus = 1 AND IFNULL(is_return, 0) = 1" + date_cond,
    tuple(args),
)
returns_total = float(returns_row[0][0] or 0) if returns_row else 0

payment_cond = ""
payment_args = []
if dfrom:
    payment_cond = payment_cond + " AND posting_date >= %s"
    payment_args.append(dfrom)
if dto:
    payment_cond = payment_cond + " AND posting_date <= %s"
    payment_args.append(dto)

paid_row = frappe.db.sql(
    "SELECT COALESCE(SUM(paid_amount), 0) FROM `tabPayment Entry` "
    "WHERE docstatus = 1 AND payment_type = 'Receive'" + payment_cond,
    tuple(payment_args),
)
paid_total = float(paid_row[0][0] or 0) if paid_row else 0

entries = []
invoice_rows = frappe.db.sql(
    "SELECT name, customer_name, grand_total, posting_date, creation, IFNULL(is_return, 0) AS is_return "
    "FROM `tabSales Invoice` "
    "WHERE docstatus = 1" + date_cond + " "
    "ORDER BY posting_date DESC, creation DESC LIMIT 100",
    tuple(args),
    as_dict=True,
)
for r in invoice_rows:
    is_return = frappe.utils.cint(r.get("is_return") or 0)
    amount = abs(float(r.get("grand_total") or 0))
    entries.append({
        "type": "return" if is_return else "invoice",
        "title": "مرتجع" if is_return else "فاتورة بيع",
        "reference": r.get("name"),
        "party": r.get("customer_name"),
        "date": str(r.get("posting_date") or ""),
        "amount": amount,
        "creation": str(r.get("creation") or ""),
    })

payment_rows = frappe.db.sql(
    "SELECT name, party_name, paid_amount, posting_date, creation "
    "FROM `tabPayment Entry` "
    "WHERE docstatus = 1 AND payment_type = 'Receive'" + payment_cond + " "
    "ORDER BY posting_date DESC, creation DESC LIMIT 100",
    tuple(payment_args),
    as_dict=True,
)
for r in payment_rows:
    entries.append({
        "type": "payment",
        "title": "تحصيل",
        "reference": r.get("name"),
        "party": r.get("party_name"),
        "date": str(r.get("posting_date") or ""),
        "amount": float(r.get("paid_amount") or 0),
        "creation": str(r.get("creation") or ""),
    })

entries = sorted(
    entries,
    key=lambda x: ((x.get("date") or ""), (x.get("creation") or "")),
    reverse=True,
)[:200]
for e in entries:
    e.pop("creation", None)

frappe.response["message"] = {
    "currency": currency,
    "sales_total": sales_total,
    "paid_total": paid_total,
    "outstanding_total": outstanding_total,
    "returns_total": returns_total,
    "entries": entries,
}
'''


THEMES_SCRIPT = r'''
# سيمات المتجر — صفحات Builder. المفعّلة هي اللي route بتاعها "shop".
title_to_slug = {"دكاني بوتيك": "boutique", "دكاني مينيمال": "minimal", "دكاني دافئ": "warm"}
rows = frappe.get_all("Builder Page", fields=["page_title", "route"])
out = []
for r in rows:
    t = r.get("page_title")
    if t in title_to_slug:
        out.append({"title": t, "slug": title_to_slug[t], "active": r.get("route") == "shop"})
frappe.response["message"] = out
'''


SET_THEME_SCRIPT = r'''
# تفعيل سيم — تخليه صفحة /shop المنشورة، والحالي يرجع لـ themes/<slug>.
can_manage_website = False
for role in ["Merchant Owner", "Website Manager", "System Manager"]:
    if frappe.db.exists(
        "Has Role",
        {
            "parent": frappe.session.user,
            "parenttype": "User",
            "role": role,
        },
    ):
        can_manage_website = True
        break
if frappe.session.user != "Administrator" and not can_manage_website:
    frappe.throw("غير مصرح لك بتغيير قالب المتجر")

slug = (frappe.form_dict.get("slug") or "").strip()
slug_to_title = {"boutique": "دكاني بوتيك", "minimal": "دكاني مينيمال", "warm": "دكاني دافئ"}
title = slug_to_title.get(slug)
if not title:
    frappe.throw("سيم غير معروف")

target = frappe.db.get_value("Builder Page", {"page_title": title}, "name")
if not target:
    frappe.throw("السيم غير متاح")

# استخدم مسار Builder الرسمي؛ publish يحفظ الصفحة ويمسح كاش /shop.
target_doc = frappe.get_doc("Builder Page", target)
target_doc.publish()
frappe.db.commit()

frappe.response["message"] = {"slug": slug, "active": True}
'''


STORE_SETTINGS_SCRIPT = r'''
# إعدادات المتجر من مستندات ERPNext القياسية:
# Company + عنوان الشركة + قالب ضريبة المبيعات.
company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
if not company or not frappe.db.exists("Company", company):
    frappe.throw("شركة المتجر غير مهيأة")

doc = frappe.get_doc("Company", company)
addresses = frappe.db.sql(
    """
    SELECT a.name, a.address_line1, a.address_line2, a.city, a.state, a.pincode
    FROM `tabAddress` a
    INNER JOIN `tabDynamic Link` dl
      ON dl.parent = a.name AND dl.parenttype = 'Address'
    WHERE dl.link_doctype = 'Company' AND dl.link_name = %s
      AND IFNULL(a.disabled, 0) = 0
    ORDER BY a.is_primary_address DESC, a.modified DESC
    LIMIT 1
    """,
    (company,),
    as_dict=True,
)
address = addresses[0] if addresses else {}

tax_rate = None
templates = frappe.get_all(
    "Sales Taxes and Charges Template",
    filters={"company": company, "disabled": 0},
    fields=["name"],
    order_by="is_default desc, modified desc",
    limit_page_length=1,
)
if templates:
    template = frappe.get_doc("Sales Taxes and Charges Template", templates[0].name)
    if template.taxes:
        tax_rate = float(template.taxes[0].rate or 0)

frappe.response["message"] = {
    "store_name": doc.company_name or doc.name,
    "logo": doc.company_logo or "",
    "phone": doc.phone_no or "",
    "email": doc.email or "",
    "description": doc.company_description or "",
    "website": doc.website or "",
    "currency": doc.default_currency or "",
    "country": doc.country or "",
    "tax_id": doc.tax_id or "",
    "tax_rate": tax_rate,
    "address_id": address.get("name") or "",
    "street": address.get("address_line1") or "",
    "district": address.get("address_line2") or "",
    "city": address.get("city") or "",
    "state": address.get("state") or "",
    "postal_code": address.get("pincode") or "",
}
'''


SAVE_STORE_SETTINGS_SCRIPT = r'''
# تعديل إعدادات المتجر في نفس مستندات ERPNext التي تستخدمها شاشة Company.
is_owner = frappe.db.exists(
    "Has Role",
    {"parent": frappe.session.user, "parenttype": "User", "role": "Merchant Owner"},
) or frappe.db.exists(
    "Has Role",
    {"parent": frappe.session.user, "parenttype": "User", "role": "System Manager"},
)
if frappe.session.user != "Administrator" and not is_owner:
    frappe.throw("غير مصرح لك بتعديل إعدادات المتجر")

company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
if not company or not frappe.db.exists("Company", company):
    frappe.throw("شركة المتجر غير مهيأة")

store_name = (frappe.form_dict.get("store_name") or "").strip()
if len(store_name) < 2:
    frappe.throw("اسم المتجر مطلوب (حرفان على الأقل)")

email = (frappe.form_dict.get("email") or "").strip()
if email and "@" not in email:
    frappe.throw("البريد الإلكتروني غير صالح")

if store_name != company:
    if frappe.db.exists("Company", store_name):
        frappe.throw("اسم المتجر مستخدم بالفعل")
    frappe.rename_doc("Company", company, store_name, force=True, ignore_permissions=True)
    company = store_name

doc = frappe.get_doc("Company", company)
doc.company_name = store_name
doc.company_logo = (frappe.form_dict.get("logo") or "").strip()
doc.phone_no = (frappe.form_dict.get("phone") or "").strip()
doc.email = email
doc.company_description = (frappe.form_dict.get("description") or "").strip()
doc.website = (frappe.form_dict.get("website") or "").strip()
doc.tax_id = (frappe.form_dict.get("tax_id") or "").strip()
doc.save(ignore_permissions=True)

address_id = (frappe.form_dict.get("address_id") or "").strip()
street = (frappe.form_dict.get("street") or "").strip()
district = (frappe.form_dict.get("district") or "").strip()
city = (frappe.form_dict.get("city") or "").strip()
state = (frappe.form_dict.get("state") or "").strip()
postal_code = (frappe.form_dict.get("postal_code") or "").strip()

address = None
if address_id and frappe.db.exists("Address", address_id):
    linked = frappe.db.exists(
        "Dynamic Link",
        {
            "parent": address_id,
            "parenttype": "Address",
            "link_doctype": "Company",
            "link_name": company,
        },
    )
    if linked:
        address = frappe.get_doc("Address", address_id)

if not address:
    rows = frappe.db.sql(
        """
        SELECT a.name
        FROM `tabAddress` a
        INNER JOIN `tabDynamic Link` dl
          ON dl.parent = a.name AND dl.parenttype = 'Address'
        WHERE dl.link_doctype = 'Company' AND dl.link_name = %s
          AND IFNULL(a.disabled, 0) = 0
        ORDER BY a.is_primary_address DESC, a.modified DESC
        LIMIT 1
        """,
        (company,),
        as_dict=True,
    )
    if rows:
        address = frappe.get_doc("Address", rows[0].name)

if address or street or city:
    if not address:
        address = frappe.new_doc("Address")
        address.address_title = store_name
        address.address_type = "Shop"
        address.is_your_company_address = 1
        address.is_primary_address = 1
        address.append(
            "links",
            {"link_doctype": "Company", "link_name": company},
        )
    address.address_title = store_name
    address.address_line1 = street or store_name
    address.address_line2 = district
    address.city = city or doc.country or "—"
    address.state = state
    address.pincode = postal_code
    address.country = doc.country
    address.email_id = email
    address.phone = doc.phone_no
    if address.is_new():
        address.insert(ignore_permissions=True)
    else:
        address.save(ignore_permissions=True)
    address_id = address.name

rate_raw = frappe.form_dict.get("tax_rate")
if rate_raw is not None and str(rate_raw).strip() != "":
    try:
        tax_rate = float(rate_raw)
    except Exception:
        frappe.throw("نسبة الضريبة غير صالحة")
    if tax_rate < 0 or tax_rate > 100:
        frappe.throw("نسبة الضريبة يجب أن تكون بين 0 و100")
    templates = frappe.get_all(
        "Sales Taxes and Charges Template",
        filters={"company": company, "disabled": 0},
        fields=["name"],
        order_by="is_default desc, modified desc",
        limit_page_length=1,
    )
    if templates:
        template = frappe.get_doc("Sales Taxes and Charges Template", templates[0].name)
        if template.taxes:
            template.taxes[0].rate = tax_rate
            template.taxes[0].description = "VAT " + str(tax_rate) + "%"
            template.title = "VAT " + str(tax_rate) + "%"
            template.save(ignore_permissions=True)

frappe.db.commit()

# إعادة نفس العقد بعد الحفظ.
doc = frappe.get_doc("Company", company)
address = frappe.get_doc("Address", address_id) if address_id and frappe.db.exists("Address", address_id) else None
tax_rate = None
templates = frappe.get_all(
    "Sales Taxes and Charges Template",
    filters={"company": company, "disabled": 0},
    fields=["name"],
    order_by="is_default desc, modified desc",
    limit_page_length=1,
)
if templates:
    template = frappe.get_doc("Sales Taxes and Charges Template", templates[0].name)
    if template.taxes:
        tax_rate = float(template.taxes[0].rate or 0)

frappe.response["message"] = {
    "store_name": doc.company_name or doc.name,
    "logo": doc.company_logo or "",
    "phone": doc.phone_no or "",
    "email": doc.email or "",
    "description": doc.company_description or "",
    "website": doc.website or "",
    "currency": doc.default_currency or "",
    "country": doc.country or "",
    "tax_id": doc.tax_id or "",
    "tax_rate": tax_rate,
    "address_id": address.name if address else "",
    "street": address.address_line1 if address else "",
    "district": address.address_line2 if address else "",
    "city": address.city if address else "",
    "state": address.state if address else "",
    "postal_code": address.pincode if address else "",
}
'''


PROFILE_SCRIPT = r'''
# بروفايل التاجر — الاسم/الجوال من User، واسم المتجر من الشركة الافتراضية.
user = frappe.session.user
row = frappe.db.get_value("User", user, ["full_name", "mobile_no"], as_dict=True) or {}
company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
frappe.response["message"] = {
    "full_name": row.get("full_name") or "",
    "mobile_no": row.get("mobile_no") or "",
    "store_name": company,
}
'''


UPDATE_PROFILE_SCRIPT = r'''
# تعديل البروفايل — الاسم/الجوال/الباسورد على User، واسم المتجر بـ rename للشركة.
# الباسورد الجديد بس (المستخدم داخل بجلسته — مثبت إنه صاحب الحساب؛
# safe_exec مبيتيحش التحقق من القديم).
user = frappe.session.user
full_name = (frappe.form_dict.get("full_name") or "").strip()
mobile_no = (frappe.form_dict.get("mobile_no") or "").strip()
store_name = (frappe.form_dict.get("store_name") or "").strip()
new_password = frappe.form_dict.get("new_password") or ""

doc = frappe.get_doc("User", user)
if full_name:
    doc.first_name = full_name
    doc.last_name = ""
if mobile_no:
    doc.mobile_no = mobile_no
if new_password:
    doc.new_password = new_password
doc.save(ignore_permissions=True)

# ⚠️ حفظ User بيعيد تطبيق الـ Role Profile وبيشيل الأدوار المضافة يدوياً
# — منها Website Manager اللي الـ resolver بيعتمد عليه (إيميل→موقع) و Merchant Owner.
# من غير ده، تعديل البروفايل بيقفل التاجر بره التطبيق. نعيد إدراجهم مباشرة
# (زي ما التجهيز بيعمل لـ Merchant Owner) لأن الإدراج المباشر بيتفادى تنظيف الأدوار.
for role in ["Website Manager", "Merchant Owner"]:
    if frappe.db.exists("Role", role) and not frappe.db.exists(
            "Has Role", {"parent": user, "role": role, "parenttype": "User"}):
        frappe.get_doc({"doctype": "Has Role", "parent": user, "parenttype": "User",
                        "parentfield": "roles", "role": role}).insert(ignore_permissions=True)

if store_name:
    company = frappe.db.get_single_value("Global Defaults", "default_company") or ""
    if company and store_name != company:
        # rename_doc بيحدّث كل الروابط (منها default_company في Global Defaults).
        frappe.rename_doc("Company", company, store_name, force=True, ignore_permissions=True)

frappe.db.commit()

company2 = frappe.db.get_single_value("Global Defaults", "default_company") or ""
row = frappe.db.get_value("User", user, ["full_name", "mobile_no"], as_dict=True) or {}
frappe.response["message"] = {
    "full_name": row.get("full_name") or "",
    "mobile_no": row.get("mobile_no") or "",
    "store_name": company2,
}
'''


TEAM_SCRIPT = r'''
# فريق العمل — ERPNext User + أدوار دكاني.
q = (frappe.form_dict.get("q") or "").strip()

role_order = ["Merchant Owner", "Store Manager", "Store Staff"]
role_key = {
    "Merchant Owner": "owner",
    "Store Manager": "manager",
    "Store Staff": "staff",
}

conds = "u.name NOT IN ('Administrator', 'Guest') AND u.user_type = 'System User'"
args = []
if q:
    like = "%" + q + "%"
    conds = conds + " AND (u.name LIKE %s OR u.full_name LIKE %s OR u.mobile_no LIKE %s)"
    args.extend([like, like, like])

rows = frappe.db.sql(
    "SELECT u.name, u.email, u.full_name, u.mobile_no, u.enabled, u.last_active "
    "FROM `tabUser` u WHERE " + conds + " ORDER BY u.enabled DESC, u.creation ASC",
    tuple(args),
    as_dict=True,
)

items = []
for u in rows:
    roles = [
        r.get("role") for r in frappe.get_all(
            "Has Role",
            filters={"parent": u.get("name"), "parenttype": "User"},
            fields=["role"],
        )
    ]
    selected = ""
    for role in role_order:
        if role in roles:
            selected = role
            break
    if not selected:
        continue
    items.append({
        "email": u.get("name"),
        "full_name": u.get("full_name") or u.get("email") or u.get("name"),
        "mobile": u.get("mobile_no") or "",
        "enabled": int(u.get("enabled") or 0),
        "last_active": str(u.get("last_active") or ""),
        "role": role_key.get(selected) or selected,
    })

frappe.response["message"] = {"items": items}
'''


SAVE_TEAM_MEMBER_SCRIPT = r'''
# إضافة عضو فريق كـ ERPNext User.
email = (frappe.form_dict.get("email") or "").strip().lower()
full_name = (frappe.form_dict.get("full_name") or "").strip()
mobile = (frappe.form_dict.get("mobile") or "").strip()
password = frappe.form_dict.get("password") or ""
role_key = (frappe.form_dict.get("role") or "staff").strip()

role_map = {
    "manager": ("Store Manager", "Dukkani Store Manager", ["Sales User", "Stock Manager", "Item Manager"]),
    "staff": ("Store Staff", "Dukkani Cashier", ["Sales User"]),
}
if role_key not in role_map:
    frappe.throw("الدور غير صحيح")
role, profile, standard_roles = role_map[role_key]

if not email or "@" not in email:
    frappe.throw("البريد الإلكتروني غير صحيح")
if not full_name:
    frappe.throw("اسم العضو مطلوب")
if len(password) < 8:
    frappe.throw("كلمة المرور لا تقل عن 8 أحرف")

if frappe.db.exists("User", email):
    frappe.throw("هذا البريد مستخدم بالفعل")

doc = frappe.new_doc("User")
doc.email = email
doc.first_name = full_name
doc.last_name = ""
doc.full_name = full_name
doc.user_type = "System User"
doc.enabled = 1
doc.send_welcome_email = 0
doc.mobile_no = mobile
doc.new_password = password
if frappe.db.exists("Role Profile", profile):
    doc.role_profile_name = profile
for r in standard_roles:
    if frappe.db.exists("Role", r):
        doc.append("roles", {"role": r})
doc.insert(ignore_permissions=True)

for r in [role, "Website Manager"]:
    if frappe.db.exists("Role", r) and not frappe.db.exists(
            "Has Role", {"parent": email, "role": r, "parenttype": "User"}):
        frappe.get_doc({"doctype": "Has Role", "parent": email, "parenttype": "User",
                        "parentfield": "roles", "role": r}).insert(ignore_permissions=True)

frappe.db.commit()

fresh = frappe.get_doc("User", email)
frappe.response["message"] = {
    "email": fresh.name,
    "full_name": fresh.full_name or fresh.name,
    "mobile": fresh.mobile_no or "",
    "enabled": int(fresh.enabled or 0),
    "last_active": str(fresh.last_active or ""),
    "role": role_key,
}
'''


TEAM_MEMBER_STATUS_SCRIPT = r'''
# تفعيل/تعطيل عضو فريق ERPNext User.
email = (frappe.form_dict.get("email") or "").strip().lower()
enabled = 1 if frappe.utils.cint(frappe.form_dict.get("enabled")) else 0
if not email or not frappe.db.exists("User", email):
    frappe.throw("عضو الفريق غير موجود")
if email in ["Administrator", "Guest", frappe.session.user]:
    frappe.throw("لا يمكن تغيير حالة هذا المستخدم من هنا")

roles = [
    r.get("role") for r in frappe.get_all(
        "Has Role",
        filters={"parent": email, "parenttype": "User"},
        fields=["role"],
    )
]
if not any(r in roles for r in ["Merchant Owner", "Store Manager", "Store Staff"]):
    frappe.throw("عضو الفريق غير موجود")

frappe.db.set_value("User", email, "enabled", enabled)
frappe.db.commit()

role = "staff"
if "Merchant Owner" in roles:
    role = "owner"
elif "Store Manager" in roles:
    role = "manager"

row = frappe.db.get_value(
    "User", email, ["full_name", "mobile_no", "enabled", "last_active"], as_dict=True) or {}
frappe.response["message"] = {
    "email": email,
    "full_name": row.get("full_name") or email,
    "mobile": row.get("mobile_no") or "",
    "enabled": int(row.get("enabled") or 0),
    "last_active": str(row.get("last_active") or ""),
    "role": role,
}
'''


ROLE_PERMISSIONS_SCRIPT = r'''
# الأدوار والصلاحيات — قراءة فعلية من ERPNext DocPerm للأدوار الثلاثة.
roles = [
    {
        "key": "owner",
        "role": "Merchant Owner",
        "name": "مالك المتجر",
        "description": "صلاحية كاملة لإدارة المتجر والماليات والمخزون.",
    },
    {
        "key": "manager",
        "role": "Store Manager",
        "name": "مدير المتجر",
        "description": "إدارة التشغيل اليومي بدون حذف أو صلاحيات مالية كاملة.",
    },
    {
        "key": "staff",
        "role": "Store Staff",
        "name": "موظف المتجر",
        "description": "صلاحيات أساسية للمنتجات والطلبات والتسليم.",
    },
]
doctypes = [
    ("Item", "المنتجات"),
    ("Item Group", "التصنيفات"),
    ("Customer", "العملاء"),
    ("Sales Order", "الطلبات"),
    ("Sales Invoice", "الفواتير"),
    ("Delivery Note", "التسليم"),
    ("Payment Entry", "المدفوعات"),
    ("Pricing Rule", "الكوبونات والخصومات"),
    ("Stock Entry", "تحويلات المخزون"),
]

result = []
for info in roles:
    perms = []
    for doctype, label in doctypes:
        rows = frappe.db.sql("""
            SELECT
                MAX(`read`) AS can_read,
                MAX(`write`) AS can_write,
                MAX(`create`) AS can_create,
                MAX(`delete`) AS can_delete,
                MAX(`submit`) AS can_submit,
                MAX(`cancel`) AS can_cancel
            FROM `tabDocPerm`
            WHERE parent = %s AND role = %s
        """, (doctype, info["role"]), as_dict=True)
        row = rows[0] if rows else {}
        perms.append({
            "doctype": doctype,
            "label": label,
            "read": int(row.get("can_read") or 0),
            "write": int(row.get("can_write") or 0),
            "create": int(row.get("can_create") or 0),
            "delete": int(row.get("can_delete") or 0),
            "submit": int(row.get("can_submit") or 0),
            "cancel": int(row.get("can_cancel") or 0),
        })
    result.append({
        "key": info["key"],
        "name": info["name"],
        "description": info["description"],
        "permissions": perms,
    })

frappe.response["message"] = {"roles": result}
'''


ACTIVITY_LOG_SCRIPT = r'''
# سجل النشاطات — قراءة من ERPNext Activity Log.
q = (frappe.form_dict.get("q") or "").strip()
atype = (frappe.form_dict.get("type") or "").strip()

if not frappe.db.exists("DocType", "Activity Log"):
    frappe.response["message"] = {"items": []}
else:
    conds = "1=1"
    args = []
    if atype:
        conds = conds + " AND operation = %s"
        args.append(atype)
    if q:
        like = "%" + q + "%"
        conds = conds + (
            " AND (subject LIKE %s OR user LIKE %s OR reference_name LIKE %s "
            "OR reference_doctype LIKE %s OR operation LIKE %s)"
        )
        args.extend([like, like, like, like, like])

    rows = frappe.db.sql(
        "SELECT name, subject, user, operation, creation, "
        "reference_doctype, reference_name "
        "FROM `tabActivity Log` WHERE " + conds + " "
        "ORDER BY creation DESC LIMIT 100",
        tuple(args),
        as_dict=True,
    )

    items = []
    for r in rows:
        items.append({
            "id": r.get("name"),
            "subject": r.get("subject") or "",
            "user": r.get("user") or "",
            "operation": r.get("operation") or "",
            "created_at": str(r.get("creation") or ""),
            "reference_type": r.get("reference_doctype") or "",
            "reference_name": r.get("reference_name") or "",
        })

    frappe.response["message"] = {"items": items}
'''


REVIEWS_LIST_SCRIPT = r'''
# قائمة تقييمات المتجر من Comments المرتبطة بالـ Item.
# التقييمات الجديدة تأتي من المتجر العام بمقدمة DUKKANI_REVIEW.
status = (frappe.form_dict.get("status") or "").strip()
if status not in ["pending", "approved", ""]:
    status = ""

rows = frappe.db.sql("""
    SELECT
        name,
        reference_name,
        comment_by,
        comment_email,
        creation,
        modified,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS reviewer_name,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS email,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS rating,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS comment_text,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS reply,
        JSON_EXTRACT(SUBSTRING(content, 16), %s) AS approved_raw
    FROM `tabComment`
    WHERE reference_doctype = %s AND comment_type = %s AND content LIKE %s
    ORDER BY creation DESC
    LIMIT 200
""", ("$.name", "$.email", "$.rating", "$.comment", "$.reply", "$.approved",
      "Item", "Comment", "DUKKANI_REVIEW:%"), as_dict=True)

items = []
for row in rows:
    approved_raw = str(row.get("approved_raw") or "").lower()
    approved = 1 if approved_raw in ["true", "1"] else 0
    if status == "pending" and approved:
        continue
    if status == "approved" and not approved:
        continue
    product_name = frappe.db.get_value("Item", row.get("reference_name"), "item_name") or row.get("reference_name")
    items.append({
        "id": row.get("name"),
        "product_id": row.get("reference_name"),
        "product_name": product_name,
        "reviewer_name": row.get("reviewer_name") or row.get("comment_by") or "عميل",
        "customer_name": row.get("reviewer_name") or row.get("comment_by") or "عميل",
        "email": row.get("email") or row.get("comment_email") or "",
        "rating": frappe.utils.cint(row.get("rating") or 0),
        "comment": row.get("comment_text") or "",
        "reply": row.get("reply") or "",
        "is_approved": approved,
        "created_at": str(row.get("creation")),
    })

frappe.response["message"] = {"items": items, "total": len(items)}
'''


REVIEW_DETAIL_SCRIPT = r'''
# تفاصيل تقييم واحد.
review_id = (frappe.form_dict.get("id") or "").strip()
if not review_id:
    frappe.throw("التقييم مطلوب")
if not frappe.db.exists("Comment", review_id):
    frappe.throw("التقييم غير موجود")

rows = frappe.db.sql("""
    SELECT
        name,
        reference_name,
        comment_by,
        comment_email,
        creation,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS reviewer_name,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS email,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS rating,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS comment_text,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(content, 16), %s)) AS reply,
        JSON_EXTRACT(SUBSTRING(content, 16), %s) AS approved_raw
    FROM `tabComment`
    WHERE name = %s AND reference_doctype = %s AND content LIKE %s
    LIMIT 1
""", ("$.name", "$.email", "$.rating", "$.comment", "$.reply", "$.approved",
      review_id, "Item", "DUKKANI_REVIEW:%"), as_dict=True)
if not rows:
    frappe.throw("التقييم غير موجود")
row = rows[0]
approved_raw = str(row.get("approved_raw") or "").lower()
approved = 1 if approved_raw in ["true", "1"] else 0
product_name = frappe.db.get_value("Item", row.get("reference_name"), "item_name") or row.get("reference_name")
frappe.response["message"] = {
    "id": row.get("name"),
    "product_id": row.get("reference_name"),
    "product_name": product_name,
    "reviewer_name": row.get("reviewer_name") or row.get("comment_by") or "عميل",
    "customer_name": row.get("reviewer_name") or row.get("comment_by") or "عميل",
    "email": row.get("email") or row.get("comment_email") or "",
    "rating": frappe.utils.cint(row.get("rating") or 0),
    "comment": row.get("comment_text") or "",
    "reply": row.get("reply") or "",
    "is_approved": approved,
    "created_at": str(row.get("creation")),
}
'''


REVIEW_STATUS_SCRIPT = r'''
# اعتماد/رفض تقييم. الاعتماد فقط هو الذي يظهره في المتجر العام.
review_id = (frappe.form_dict.get("id") or "").strip()
approved = frappe.utils.cint(frappe.form_dict.get("approved"))
if not review_id:
    frappe.throw("التقييم مطلوب")
if not frappe.db.exists("Comment", review_id):
    frappe.throw("التقييم غير موجود")

doc = frappe.get_doc("Comment", review_id)
content = (doc.content or "").strip()
if doc.reference_doctype != "Item" or not content.startswith("DUKKANI_REVIEW:"):
    frappe.throw("التقييم غير موجود")
if approved:
    rows = frappe.db.sql("SELECT JSON_SET(SUBSTRING(%s, 16), %s, true)", (content, "$.approved"))
else:
    rows = frappe.db.sql("SELECT JSON_SET(SUBSTRING(%s, 16), %s, false)", (content, "$.approved"))
doc.content = "DUKKANI_REVIEW:" + rows[0][0]
doc.save(ignore_permissions=True)
frappe.db.commit()

product_name = frappe.db.get_value("Item", doc.reference_name, "item_name") or doc.reference_name
content = (doc.content or "").strip()
rows = frappe.db.sql("""
    SELECT
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS reviewer_name,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS email,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS rating,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS comment_text,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS reply,
        JSON_EXTRACT(SUBSTRING(%s, 16), %s) AS approved_raw
""", (content, "$.name", content, "$.email", content, "$.rating", content, "$.comment",
      content, "$.reply", content, "$.approved"), as_dict=True)
row = rows[0]
approved_raw = str(row.get("approved_raw") or "").lower()
frappe.response["message"] = {
    "id": doc.name,
    "product_id": doc.reference_name,
    "product_name": product_name,
    "reviewer_name": row.get("reviewer_name") or doc.comment_by or "عميل",
    "customer_name": row.get("reviewer_name") or doc.comment_by or "عميل",
    "email": row.get("email") or doc.comment_email or "",
    "rating": frappe.utils.cint(row.get("rating") or 0),
    "comment": row.get("comment_text") or "",
    "reply": row.get("reply") or "",
    "is_approved": 1 if approved_raw in ["true", "1"] else 0,
    "created_at": str(doc.creation),
}
'''


REVIEW_REPLY_SCRIPT = r'''
# حفظ رد التاجر على التقييم.
review_id = (frappe.form_dict.get("id") or "").strip()
reply = (frappe.form_dict.get("reply") or "").strip()
if not review_id:
    frappe.throw("التقييم مطلوب")
if not frappe.db.exists("Comment", review_id):
    frappe.throw("التقييم غير موجود")

doc = frappe.get_doc("Comment", review_id)
content = (doc.content or "").strip()
if doc.reference_doctype != "Item" or not content.startswith("DUKKANI_REVIEW:"):
    frappe.throw("التقييم غير موجود")
rows = frappe.db.sql("SELECT JSON_SET(SUBSTRING(%s, 16), %s, %s)",
    (content, "$.reply", reply[:800]))
doc.content = "DUKKANI_REVIEW:" + rows[0][0]
doc.save(ignore_permissions=True)
frappe.db.commit()

product_name = frappe.db.get_value("Item", doc.reference_name, "item_name") or doc.reference_name
content = (doc.content or "").strip()
rows = frappe.db.sql("""
    SELECT
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS reviewer_name,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS email,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS rating,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS comment_text,
        JSON_UNQUOTE(JSON_EXTRACT(SUBSTRING(%s, 16), %s)) AS reply,
        JSON_EXTRACT(SUBSTRING(%s, 16), %s) AS approved_raw
""", (content, "$.name", content, "$.email", content, "$.rating", content, "$.comment",
      content, "$.reply", content, "$.approved"), as_dict=True)
row = rows[0]
approved_raw = str(row.get("approved_raw") or "").lower()
frappe.response["message"] = {
    "id": doc.name,
    "product_id": doc.reference_name,
    "product_name": product_name,
    "reviewer_name": row.get("reviewer_name") or doc.comment_by or "عميل",
    "customer_name": row.get("reviewer_name") or doc.comment_by or "عميل",
    "email": row.get("email") or doc.comment_email or "",
    "rating": frappe.utils.cint(row.get("rating") or 0),
    "comment": row.get("comment_text") or "",
    "reply": row.get("reply") or "",
    "is_approved": 1 if approved_raw in ["true", "1"] else 0,
    "created_at": str(doc.creation),
}
'''


def ensure_dukkani_notification(
    name,
    document_type,
    event,
    subject,
    message,
    *,
    value_changed=None,
    condition=None,
):
    """ينشئ System Notification أصلية في ERPNext ويحدّثها بأمان."""
    exists = frappe.db.exists("Notification", name)
    doc = (
        frappe.get_doc("Notification", name)
        if exists
        else frappe.new_doc("Notification")
    )
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
    if exists:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    log(f"{'تحديث' if exists else 'إنشاء'} إشعار ERPNext: {name}")


def ensure_dukkani_notifications():
    """تنبيهات التشغيل التي تظهر في ERPNext والموبايل من نفس المصدر."""
    ensure_dukkani_notification(
        "Dukkani Sales Order Status Changed",
        "Sales Order",
        "Value Change",
        "تحديث حالة الطلب #{{ doc.name }}",
        "تم تغيير حالة الطلب **#{{ doc.name }}** إلى **{{ doc.status }}**.",
        value_changed="status",
    )
    ensure_dukkani_notification(
        "Dukkani Low Stock Alert",
        "Bin",
        "Value Change",
        "المخزون أوشك على النفاد",
        (
            "متبقي **{{ doc.actual_qty }}** فقط من **{{ doc.item_code }}** "
            "في مخزن **{{ doc.warehouse }}**."
        ),
        value_changed="actual_qty",
        condition="doc.actual_qty <= 5",
    )
    ensure_dukkani_notification(
        "Dukkani New Store Review",
        "Comment",
        "New",
        "تقييم جديد على {{ doc.reference_name }}",
        "وصل تقييم جديد على **{{ doc.reference_name }}** ويحتاج المراجعة.",
        condition=(
            'doc.reference_doctype == "Item" and doc.content and '
            'doc.content.startswith("DUKKANI_REVIEW:")'
        ),
    )
    ensure_dukkani_notification(
        "Dukkani Stock Transfer Submitted",
        "Stock Entry",
        "Submit",
        "تم إتمام تحويل المخزون #{{ doc.name }}",
        "تم اعتماد تحويل المخزون **#{{ doc.name }}** بنجاح.",
        condition='doc.stock_entry_type == "Material Transfer"',
    )


def ensure_mobile_server_script(name, api_method, script):
    """بينشئ/بيحدّث Server Script من نوع API — آمن للتكرار.

    ليه Server Script مش تطبيق Frappe: عشان كام endpoint، تطبيق كامل معناه
    `bench get-app` + إعادة بناء الصورة + تثبيت على كل موقع + إدارة نسخ.
    الـ Server Script سجل في قاعدة البيانات — القالب بينشئه زي أي حاجة تانية،
    ونفس النمط مستخدم أصلاً في storefront_starter.py (Client Script).
    """
    exists = frappe.db.exists("Server Script", name)
    d = frappe.get_doc("Server Script", name) if exists else frappe.new_doc("Server Script")
    if not exists:
        d.name = name
    d.script_type = "API"
    d.api_method = api_method
    d.allow_guest = 0          # بيانات متجر — لازم مصادقة
    d.disabled = 0
    d.script = script
    d.save(ignore_permissions=True) if exists else d.insert(ignore_permissions=True)
    log(f"{'تحديث' if exists else 'إنشاء'} endpoint موبايل: {api_method}")


def ensure_mobile_dashboard():
    """endpoints الموبايل. بيتاحوا على /api/method/<api_method>."""
    ensure_mobile_server_script(
        "Dukkani Mobile Dashboard", "dukkani_mobile_dashboard", DASHBOARD_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Analytics", "dukkani_mobile_analytics", ANALYTICS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Products", "dukkani_mobile_products", PRODUCTS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Save Product", "dukkani_mobile_save_product", SAVE_PRODUCT_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Product Status", "dukkani_mobile_product_status", PRODUCT_STATUS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Item Groups", "dukkani_mobile_item_groups", ITEM_GROUPS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Save Item Group", "dukkani_mobile_save_item_group", SAVE_ITEM_GROUP_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Warehouses", "dukkani_mobile_warehouses", WAREHOUSES_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Save Warehouse", "dukkani_mobile_save_warehouse", SAVE_WAREHOUSE_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Stock Transfers", "dukkani_mobile_stock_transfers", STOCK_TRANSFERS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Save Stock Transfer", "dukkani_mobile_save_stock_transfer", SAVE_STOCK_TRANSFER_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Coupons", "dukkani_mobile_coupons", COUPONS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Save Coupon", "dukkani_mobile_save_coupon", SAVE_COUPON_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Coupon Status", "dukkani_mobile_coupon_status", COUPON_STATUS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Delete Coupon", "dukkani_mobile_delete_coupon", DELETE_COUPON_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Customers", "dukkani_mobile_customers", CUSTOMERS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Customer", "dukkani_mobile_customer", CUSTOMER_DETAIL_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Save Customer", "dukkani_mobile_save_customer", SAVE_CUSTOMER_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Delete Product", "dukkani_mobile_delete_product", DELETE_PRODUCT_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Orders", "dukkani_mobile_orders", ORDERS_LIST_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Order", "dukkani_mobile_order", ORDER_DETAIL_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Create Order", "dukkani_mobile_create_order", CREATE_ORDER_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Order Status", "dukkani_mobile_order_status", ORDER_STATUS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Invoices", "dukkani_mobile_invoices", INVOICES_LIST_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Invoice", "dukkani_mobile_invoice", INVOICE_DETAIL_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Returns", "dukkani_mobile_returns", RETURNS_LIST_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Return", "dukkani_mobile_return", RETURN_DETAIL_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Account Statement", "dukkani_mobile_account_statement", ACCOUNT_STATEMENT_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Themes", "dukkani_mobile_themes", THEMES_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Set Theme", "dukkani_mobile_set_theme", SET_THEME_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Store Settings", "dukkani_mobile_store_settings", STORE_SETTINGS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Save Store Settings", "dukkani_mobile_save_store_settings", SAVE_STORE_SETTINGS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Profile", "dukkani_mobile_profile", PROFILE_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Update Profile", "dukkani_mobile_update_profile", UPDATE_PROFILE_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Team", "dukkani_mobile_team", TEAM_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Save Team Member", "dukkani_mobile_save_team_member", SAVE_TEAM_MEMBER_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Team Member Status", "dukkani_mobile_team_member_status", TEAM_MEMBER_STATUS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Role Permissions", "dukkani_mobile_role_permissions", ROLE_PERMISSIONS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Activity Log", "dukkani_mobile_activity_log", ACTIVITY_LOG_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Reviews", "dukkani_mobile_reviews", REVIEWS_LIST_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Review", "dukkani_mobile_review", REVIEW_DETAIL_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Review Status", "dukkani_mobile_review_status", REVIEW_STATUS_SCRIPT)
    ensure_mobile_server_script(
        "Dukkani Mobile Review Reply", "dukkani_mobile_review_reply", REVIEW_REPLY_SCRIPT)


MERCHANT_REVIEWS_WEB_HTML = r'''
<div id="dukkani-merchant-reviews" dir="rtl">
  <header class="dmr-header">
    <div>
      <h1>التقييمات</h1>
      <p>راجع تقييمات العملاء واعتمد ما يظهر في المتجر.</p>
    </div>
    <a class="dmr-store" href="/shop" target="_blank">فتح المتجر</a>
  </header>
  <nav class="dmr-tabs">
    <button data-status="" class="active">الكل</button>
    <button data-status="pending">بانتظار المراجعة</button>
    <button data-status="approved">معتمد</button>
  </nav>
  <main class="dmr-layout">
    <section class="dmr-list" aria-label="قائمة التقييمات"></section>
    <section class="dmr-detail" aria-label="تفاصيل التقييم">
      <div class="dmr-empty">اختر تقييم من القائمة</div>
    </section>
  </main>
</div>
<style>
  .page-header-wrapper,.page-breadcrumbs{display:none!important}
  .page-content-wrapper,.page_content,.webpage-content,.web-page-content,.web-template-section,main{padding:0!important;margin:0!important;max-width:none!important}
  #dukkani-merchant-reviews{min-height:100vh;background:#f7f7f7;color:#111;font-family:Tajawal,Cairo,Arial,sans-serif;padding:24px}
  .dmr-header{display:flex;align-items:center;justify-content:space-between;gap:16px;max-width:1120px;margin:0 auto 18px}
  .dmr-header h1{font-size:28px;line-height:38px;margin:0;font-weight:900}
  .dmr-header p{font-size:14px;color:#757575;margin:4px 0 0}
  .dmr-store{display:inline-flex;height:44px;align-items:center;border:1px solid #e0e0e0;border-radius:10px;background:#111;color:#fff;padding:0 16px;font-weight:800;text-decoration:none}
  .dmr-tabs{display:flex;gap:8px;max-width:1120px;margin:0 auto 18px;overflow:auto}
  .dmr-tabs button{height:40px;border:1px solid #e0e0e0;border-radius:999px;background:#fff;color:#111;padding:0 18px;font:700 14px inherit;cursor:pointer;white-space:nowrap}
  .dmr-tabs button.active{background:#111;color:#fff}
  .dmr-layout{display:grid;grid-template-columns:minmax(320px,420px) 1fr;gap:16px;max-width:1120px;margin:0 auto}
  .dmr-list{display:flex;flex-direction:column;gap:12px}
  .dmr-card,.dmr-detail-card{background:#fff;border:1px solid #e0e0e0;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
  .dmr-card{padding:14px;cursor:pointer}
  .dmr-card.active{border-color:#111}
  .dmr-card-head,.dmr-line{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
  .dmr-name{font-size:14px;font-weight:900}
  .dmr-product,.dmr-muted{font-size:13px;color:#757575}
  .dmr-badge{display:inline-flex;align-items:center;gap:6px;height:24px;border:1px solid #e0e0e0;border-radius:999px;padding:0 9px;font-size:12px;background:#fff;white-space:nowrap}
  .dmr-badge::before{content:"";width:8px;height:8px;border-radius:50%;background:#f79009}
  .dmr-badge.approved::before{background:#12b76a}
  .dmr-stars{display:inline-flex;gap:2px;color:#d1d5db;font-size:18px;line-height:1;margin-top:8px}
  .dmr-stars .on{color:#f59e0b}
  .dmr-comment{font-size:13px;line-height:22px;margin:8px 0 0;color:#333}
  .dmr-detail-card{padding:18px}
  .dmr-detail h2{font-size:22px;line-height:32px;margin:0 0 4px;font-weight:900}
  .dmr-section{border-top:1px solid #eee;margin-top:16px;padding-top:16px}
  .dmr-section h3{font-size:15px;margin:0 0 10px;font-weight:900}
  .dmr-line{padding:7px 0}
  .dmr-line b{font-size:14px}
  .dmr-actions{display:flex;gap:10px;margin-top:16px}
  .dmr-actions button,.dmr-save{height:44px;border:1px solid #111;border-radius:10px;background:#111;color:#fff;padding:0 16px;font:800 14px inherit;cursor:pointer}
  .dmr-actions button.secondary{background:#fff;color:#111;border-color:#e0e0e0}
  .dmr-reply{width:100%;min-height:120px;box-sizing:border-box;border:1px solid #e0e0e0;border-radius:12px;padding:12px;font:inherit;resize:vertical;background:#fff;color:#111}
  .dmr-msg{font-size:13px;color:#757575;margin-top:10px;min-height:22px}
  .dmr-empty{background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:42px 18px;text-align:center;color:#757575}
  @media(max-width:820px){#dukkani-merchant-reviews{padding:16px}.dmr-layout{grid-template-columns:1fr}.dmr-header{align-items:flex-start;flex-direction:column}.dmr-store{width:100%;justify-content:center}}
</style>
<script>
(function(){
  const root = document.getElementById("dukkani-merchant-reviews");
  if (!root) return;
  const list = root.querySelector(".dmr-list");
  const detail = root.querySelector(".dmr-detail");
  const tabs = Array.from(root.querySelectorAll(".dmr-tabs button"));
  let reviews = [];
  let selected = null;
  let status = "";
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
  const stars = value => Array.from({length:5}, (_, i) => `<span class="${i < Number(value || 0) ? "on" : ""}">★</span>`).join("");
  async function api(method, query) {
    const params = new URLSearchParams(query || {});
    const response = await fetch(`/api/method/${method}${params.size ? "?" + params.toString() : ""}`, {credentials:"same-origin"});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || "تعذر تنفيذ الطلب");
    return data.message;
  }
  async function load() {
    list.innerHTML = '<div class="dmr-empty">جاري تحميل التقييمات...</div>';
    try {
      const data = await api("dukkani_mobile_reviews", status ? {status} : {});
      reviews = data.items || [];
      renderList();
      if (selected) {
        selected = reviews.find(r => r.id === selected.id) || null;
        renderDetail();
      }
    } catch (error) {
      list.innerHTML = `<div class="dmr-empty">${esc(error.message)}<br><a href="/login?redirect-to=/app/dukkani-reviews">تسجيل الدخول</a></div>`;
    }
  }
  function renderList() {
    if (!reviews.length) {
      list.innerHTML = '<div class="dmr-empty">لا توجد تقييمات</div>';
      return;
    }
    list.innerHTML = reviews.map(r => `<article class="dmr-card ${selected && selected.id === r.id ? "active" : ""}" data-id="${esc(r.id)}">
      <div class="dmr-card-head"><div><div class="dmr-name">${esc(r.reviewer_name || r.customer_name || "عميل")}</div><div class="dmr-product">${esc(r.product_name || "")}</div></div><span class="dmr-badge ${r.is_approved ? "approved" : ""}">${r.is_approved ? "معتمد" : "بانتظار المراجعة"}</span></div>
      <div class="dmr-stars">${stars(r.rating)}</div>
      ${r.comment ? `<p class="dmr-comment">${esc(r.comment)}</p>` : ""}
    </article>`).join("");
    list.querySelectorAll(".dmr-card").forEach(card => card.onclick = () => {
      selected = reviews.find(r => r.id === card.dataset.id);
      renderList();
      renderDetail();
    });
  }
  function renderDetail() {
    if (!selected) {
      detail.innerHTML = '<div class="dmr-empty">اختر تقييم من القائمة</div>';
      return;
    }
    detail.innerHTML = `<div class="dmr-detail-card">
      <div class="dmr-card-head"><div><h2>${esc(selected.reviewer_name || "عميل")}</h2><div class="dmr-muted">${esc(selected.product_name || "")}</div></div><span class="dmr-badge ${selected.is_approved ? "approved" : ""}">${selected.is_approved ? "معتمد" : "بانتظار المراجعة"}</span></div>
      <div class="dmr-section"><h3>التقييم</h3><div class="dmr-stars">${stars(selected.rating)}</div><p class="dmr-comment">${esc(selected.comment || "لا يوجد تعليق")}</p></div>
      <div class="dmr-section"><h3>بيانات</h3><div class="dmr-line"><span class="dmr-muted">البريد</span><b dir="ltr">${esc(selected.email || "-")}</b></div><div class="dmr-line"><span class="dmr-muted">رقم التقييم</span><b dir="ltr">${esc(selected.id)}</b></div></div>
      <div class="dmr-section"><h3>حالة الاعتماد</h3><div class="dmr-actions"><button class="approve">${selected.is_approved ? "إلغاء الاعتماد" : "اعتماد التقييم"}</button></div></div>
      <div class="dmr-section"><h3>الرد على التقييم</h3><textarea class="dmr-reply" placeholder="اكتب ردك على العميل...">${esc(selected.reply || "")}</textarea><button class="dmr-save">حفظ الرد</button><div class="dmr-msg"></div></div>
    </div>`;
    detail.querySelector(".approve").onclick = async () => {
      const button = detail.querySelector(".approve");
      button.disabled = true;
      selected = await api("dukkani_mobile_review_status", {id:selected.id, approved:selected.is_approved ? 0 : 1});
      await load();
      renderDetail();
    };
    detail.querySelector(".dmr-save").onclick = async () => {
      const msg = detail.querySelector(".dmr-msg");
      msg.textContent = "جاري الحفظ...";
      selected = await api("dukkani_mobile_review_reply", {id:selected.id, reply:detail.querySelector(".dmr-reply").value.trim()});
      msg.textContent = "تم الحفظ";
      await load();
      renderDetail();
    };
  }
  tabs.forEach(tab => tab.onclick = () => {
    tabs.forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    status = tab.dataset.status || "";
    selected = null;
    detail.innerHTML = '<div class="dmr-empty">اختر تقييم من القائمة</div>';
    load();
  });
  load();
})();
</script>
'''


def ensure_merchant_reviews_desk():
    """Create the merchant review moderation UI inside ERPNext Desk."""
    import json

    raw = MERCHANT_REVIEWS_WEB_HTML
    style_start = raw.find("<style>")
    style_end = raw.find("</style>")
    script_start = raw.find("<script>")
    script_end = raw.rfind("</script>")
    html = raw[:style_start].strip()
    style = raw[style_start + len("<style>"):style_end].strip() if style_start >= 0 else ""
    script = raw[script_start + len("<script>"):script_end].strip() if script_start >= 0 else ""

    block_name = "Dukkani Merchant Reviews"
    if frappe.db.exists("Custom HTML Block", block_name):
        block = frappe.get_doc("Custom HTML Block", block_name)
    else:
        block = frappe.new_doc("Custom HTML Block")
        block.name = block_name
    block.private = 0
    block.html = html
    block.style = style
    block.script = script
    block.set("roles", [])
    block.save(ignore_permissions=True) if frappe.db.exists("Custom HTML Block", block_name) else block.insert(ignore_permissions=True)

    workspace_name = "Dukkani Reviews"
    content = [
        {
            "id": "dkn_reviews_hdr",
            "type": "header",
            "data": {"text": '<span class="h4"><b>التقييمات</b></span>', "col": 12},
        },
        {
            "id": "dkn_reviews_block",
            "type": "custom_block",
            "data": {"custom_block_name": block_name, "col": 12},
        },
    ]
    if frappe.db.exists("Workspace", workspace_name):
        workspace = frappe.get_doc("Workspace", workspace_name)
    else:
        workspace = frappe.new_doc("Workspace")
        workspace.name = workspace_name
    workspace.label = "التقييمات"
    workspace.title = "التقييمات"
    workspace.public = 1
    workspace.is_hidden = 0
    workspace.icon = "star"
    workspace.sequence_id = 2
    workspace.content = json.dumps(content, ensure_ascii=False)
    workspace.set("custom_blocks", [])
    workspace.append("custom_blocks", {"custom_block_name": block_name, "label": block_name})
    workspace.flags.ignore_links = True
    workspace.save(ignore_permissions=True) if frappe.db.exists("Workspace", workspace_name) else workspace.insert(ignore_permissions=True)

    if frappe.db.exists("Workspace", "Dukkani"):
        main = frappe.get_doc("Workspace", "Dukkani")
        found = False
        for shortcut in main.shortcuts:
            if shortcut.label == "التقييمات":
                shortcut.type = "URL"
                shortcut.url = "/app/dukkani-reviews"
                shortcut.link_to = None
                shortcut.color = "Yellow"
                found = True
        if not found:
            main.append("shortcuts", {
                "type": "URL",
                "url": "/app/dukkani-reviews",
                "label": "التقييمات",
                "color": "Yellow",
            })
        try:
            main_content = json.loads(main.content or "[]")
        except Exception:
            main_content = []
        if not any(item.get("type") == "shortcut" and item.get("data", {}).get("shortcut_name") == "التقييمات"
                   for item in main_content):
            main_content.append({
                "id": "sc_التقييمات",
                "type": "shortcut",
                "data": {"shortcut_name": "التقييمات", "col": 3},
            })
            main.content = json.dumps(main_content, ensure_ascii=False)
        main.flags.ignore_links = True
        main.save(ignore_permissions=True)

    if frappe.db.exists("Workspace Sidebar", "Dukkani"):
        sidebar = frappe.get_doc("Workspace Sidebar", "Dukkani")
        exists = any(item.label == "التقييمات" for item in sidebar.items)
        if not exists:
            sidebar.append("items", {
                "label": "التقييمات",
                "link_to": workspace_name,
                "link_type": "Workspace",
                "type": "Link",
                "icon": "star",
                "idx": len(sidebar.items) + 1,
            })
            sidebar.flags.ignore_links = True
            sidebar.save(ignore_permissions=True)

    existing = frappe.db.get_value("Web Page", {"route": "merchant/reviews"}, "name")
    if existing:
        frappe.db.set_value("Web Page", existing, "published", 0)

    icon_values = {
        "label": "التقييمات",
        "icon_type": "Icon",
        "link_type": "Workspace",
        "link_to": workspace_name,
        "app": "erpnext",
        "icon": "star",
        "link": "",
        "hidden": 0,
        "idx": 95,
    }
    icon_name = (
        frappe.db.get_value("Desktop Icon", {"link": "/merchant/reviews"}, "name")
        or frappe.db.get_value("Desktop Icon", {"label": "التقييمات"}, "name")
    )
    if icon_name:
        frappe.db.set_value("Desktop Icon", icon_name, icon_values)
    else:
        frappe.get_doc({"doctype": "Desktop Icon", **icon_values}).insert(ignore_permissions=True)
    log("تحديث شاشة التقييمات داخل ERPNext Desk: /app/dukkani-reviews")


def apply_template():
    print("\n===== تطبيق قالب دكاني على موقع التاجر =====")
    print(f"   التاجر: {MERCHANT_NAME}  |  الاختصار: {MERCHANT_ABBR}")
    # نتخطى الإشعارات/الإيميلات أثناء التجهيز (تفادي قوالب Notification المعطوبة في مواقع جديدة)
    frappe.flags.in_import = True
    frappe.flags.mute_emails = True
    frappe.db.sql("UPDATE `tabNotification` SET enabled=0")
    frappe.clear_cache()
    log("تم تعطيل الإشعارات مؤقتاً أثناء التجهيز.")
    ensure_prerequisites()
    company = ensure_company()
    ensure_fiscal_year()
    set_global_defaults(company)
    ensure_customer_signup_enabled()
    frappe.db.commit()   # نثبّت علامة اكتمال الإعداد فورًا (متتراجعش لو خطوة لاحقة فشلت)
    ensure_roles()
    ensure_dukkani_notifications()
    ensure_payment_modes(company)
    ensure_vat_template(company, MERCHANT_ABBR)
    ensure_base_masters(company)
    ensure_dukkani_look()
    ensure_dukkani_grid()
    ensure_role_profiles()
    # إنشاء يوزر المالك محمي: لو فشل لأي سبب، منوقفش تجهيز باقي المتجر
    try:
        ensure_owner_user()
    except Exception as e:
        log(f"⚠️ تعذّر إنشاء يوزر المالك ({e}) — المتجر جاهز، اعمل اليوزر يدويًا لاحقًا.")
    ensure_store_display_name()
    ensure_naming_series()
    # الداشبورد محمي زي يوزر المالك: المتجر لازم يشتغل حتى لو الموبايل
    # مش هيلاقي الـ endpoint.
    try:
        ensure_mobile_dashboard()
    except Exception as e:
        log(f"⚠️ تعذّر إنشاء endpoint داشبورد الموبايل ({e}) — المتجر جاهز، الويب مش متأثر.")
    try:
        ensure_merchant_reviews_desk()
    except Exception as e:
        log(f"⚠️ تعذّر إنشاء شاشة التقييمات داخل ERPNext ({e}) — الموبايل والمتجر شغالين.")
    frappe.db.commit()
    print("===== ✅ اكتمل تطبيق القالب بنجاح =====\n")

if globals().get("DUKKANI_APPLY_TEMPLATE", True):
    apply_template()
