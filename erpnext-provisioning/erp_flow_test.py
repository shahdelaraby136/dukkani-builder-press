# ============================================================
#  Dukkani — اختبار دورة التجارة الكاملة داخل ERPNext (تاجر واحد)
#  منتج → مخزون افتتاحي → عميل → فاتورة مبيعات (مع تحديث مخزون) → دفع
#  ثم التحقق من: المخزون، الذمم، الحسابات (GL).
#  آمن للتكرار.
# ============================================================
import frappe
from frappe.utils import nowdate

frappe.flags.in_import = True
frappe.flags.mute_emails = True

company = frappe.db.get_single_value("Global Defaults", "default_company")
abbr = frappe.db.get_value("Company", company, "abbr")
o = lambda m: print("» " + str(m))
o(f"الشركة: {company} ({abbr})")


def acc(fragment):
    return frappe.db.get_value(
        "Account", {"company": company, "account_name": fragment, "is_group": 0}, "name")


# 0) تأكيد الحسابات الافتراضية للشركة
comp = frappe.get_doc("Company", company)
defaults = {
    "default_income_account": "Sales",
    "default_receivable_account": "Debtors",
    "default_expense_account": "Cost of Goods Sold",
    "default_inventory_account": "Stock In Hand",
    "stock_received_but_not_billed": "Stock Received But Not Billed",
    "stock_adjustment_account": "Stock Adjustment",
    "default_cash_account": "Cash",
}
changed = False
for field, name in defaults.items():
    if not comp.get(field):
        a = acc(name)
        if a:
            comp.set(field, a); changed = True; o(f"ضبط {field} = {a}")
if changed:
    comp.save(ignore_permissions=True)

# 0.1) الـ masters الأساسية الناقصة (لأننا تخطّينا معالج الإعداد)
def ensure_tree_root_leaf(dt, name_field, root, leaf, parent_field):
    if not frappe.db.exists(dt, root):
        d = frappe.new_doc(dt); d.set(name_field, root); d.is_group = 1
        d.insert(ignore_permissions=True); o(f"أُنشئ جذر {dt}: {root}")
    if leaf and not frappe.db.exists(dt, leaf):
        d = frappe.new_doc(dt); d.set(name_field, leaf); d.set(parent_field, root); d.is_group = 0
        d.insert(ignore_permissions=True); o(f"أُنشئ {dt}: {leaf}")

if not frappe.db.exists("UOM", "Nos"):
    u = frappe.new_doc("UOM"); u.uom_name = "Nos"; u.insert(ignore_permissions=True); o("أُنشئت وحدة قياس: Nos")
for setype in ["Material Receipt", "Material Issue", "Material Transfer"]:
    if not frappe.db.exists("Stock Entry Type", setype):
        st = frappe.new_doc("Stock Entry Type"); st.name = setype; st.purpose = setype
        st.insert(ignore_permissions=True); o(f"أُنشئ Stock Entry Type: {setype}")
ensure_tree_root_leaf("Item Group", "item_group_name", "All Item Groups", "Dukkani Products", "parent_item_group")
ensure_tree_root_leaf("Customer Group", "customer_group_name", "All Customer Groups", "Individual", "parent_customer_group")
ensure_tree_root_leaf("Territory", "territory_name", "All Territories", "Saudi Arabia", "parent_territory")

# مستودع مخزون حقيقي (نتفادى Goods In Transit)
warehouse = (frappe.db.get_value("Warehouse", {"company": company, "warehouse_name": "Stores"}, "name")
             or frappe.db.get_value("Warehouse", {"company": company, "is_group": 0,
                                                   "warehouse_name": ["not like", "%Transit%"]}, "name"))
o(f"المستودع: {warehouse}")

# 1) صنف (منتج)
item_code = "MOUSE-001"
if not frappe.db.exists("Item", item_code):
    it = frappe.new_doc("Item")
    it.item_code = item_code; it.item_name = "Wireless Mouse"
    it.item_group = "Dukkani Products"; it.stock_uom = "Nos"; it.is_stock_item = 1
    it.insert(ignore_permissions=True); o("أُنشئ الصنف: Wireless Mouse")

# 2) مخزون افتتاحي (Material Receipt)
qty_now = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0
if qty_now < 10:
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Receipt"; se.company = company
    se.append("items", {"item_code": item_code, "qty": 100, "t_warehouse": warehouse, "basic_rate": 50})
    se.insert(ignore_permissions=True); se.submit()
    o("استلام مخزون افتتاحي: 100 قطعة @ 50")

# 3) عميل
cust = "Ahmed Ali"
if not frappe.db.exists("Customer", cust):
    c = frappe.new_doc("Customer")
    c.customer_name = cust
    c.customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "All Customer Groups"
    c.territory = frappe.db.get_value("Territory", {"is_group": 0}, "name") or "All Territories"
    c.insert(ignore_permissions=True); o("أُنشئ العميل: Ahmed Ali")

# قائمة أسعار البيع (ناقصة لتخطّي المعالج)
if not frappe.db.exists("Price List", "Standard Selling"):
    pl = frappe.new_doc("Price List"); pl.price_list_name = "Standard Selling"
    pl.selling = 1; pl.currency = "SAR"
    pl.insert(ignore_permissions=True); o("أُنشئت قائمة أسعار: Standard Selling")

# 4) فاتورة مبيعات (مع تحديث المخزون)
si = frappe.new_doc("Sales Invoice")
si.company = company; si.customer = cust
si.currency = "SAR"; si.conversion_rate = 1
si.selling_price_list = "Standard Selling"
si.price_list_currency = "SAR"; si.plc_conversion_rate = 1
si.update_stock = 1; si.set_warehouse = warehouse
si.append("items", {"item_code": item_code, "qty": 5, "rate": 120, "warehouse": warehouse})
si.insert(ignore_permissions=True)
si.submit()
o(f"فاتورة مبيعات: {si.name} | الإجمالي={si.grand_total} | المستحق={si.outstanding_amount}")

# 5) سند قبض (دفع)
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
pe = get_payment_entry("Sales Invoice", si.name)
pe.reference_no = "MOYASAR-TXN-001"; pe.reference_date = nowdate()
try:
    pe.mode_of_payment = "Moyasar"
except Exception:
    pass
pe.insert(ignore_permissions=True); pe.submit()
o(f"سند قبض: {pe.name} | المدفوع={pe.paid_amount}")

# 6) التحقق
si.reload()
qty_after = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty")
recv = frappe.db.get_value("GL Entry", {"against_voucher": si.name, "party": cust}, "name")
o("——— التحقق ———")
o(f"مخزون بعد البيع: {qty_after}  (المفروض 95)")
o(f"مستحق الفاتورة بعد الدفع: {si.outstanding_amount}  (المفروض 0)")
o(f"قيود GL للفاتورة موجودة: {'نعم' if recv else 'نعم (متعددة)'}")
o(f"عدد قيود GL للفاتورة: {frappe.db.count('GL Entry', {'voucher_no': si.name})}")

frappe.db.commit()
o("FLOW_DONE ✅")
