"""Install Dukkani Builder storefront starters on the current Frappe site.

Run through ``bench --site <site> console`` after installing the Builder app.
Set ``SEED_DEMO_PRODUCTS=1`` to add the Noor perfume demo catalogue.
The script is idempotent so provisioning can safely retry it.
"""

import json
import os

import frappe
from builder.utils import Block


OWNER_EMAIL = os.environ.get("MERCHANT_EMAIL", "").strip().lower()
SEED_DEMO_PRODUCTS = os.environ.get("SEED_DEMO_PRODUCTS", "0") == "1"
STOREFRONT_CART_PATH = os.environ.get("STOREFRONT_CART_PATH", "/tmp/storefront_cart.js")
STOREFRONT_SCRIPT_NAME = "Dukkani Storefront Commerce"


# Public-domain / CC0 product photographs from Wikimedia Commons.
DEMO_PRODUCTS = [
    ("NOOR-AMBER", "عطر عنبر شرقي", 890, "نفحات عنبر دافئة بلمسة فانيليا وخشب.",
     "https://commons.wikimedia.org/wiki/Special:Redirect/file/Perfume_Bottle.jpg?width=900"),
    ("NOOR-AQUA", "عطر أكوا", 720, "رائحة منعشة وخفيفة للاستخدام اليومي.",
     "https://commons.wikimedia.org/wiki/Special:Redirect/file/Perfume_Bottle_MET_DP242904.jpg?width=900"),
    ("NOOR-ROSE", "عطر ورد ملكي", 950, "مزيج أنيق من الورد والمسك الأبيض.",
     "https://commons.wikimedia.org/wiki/Special:Redirect/file/Perfume_Bottle_LACMA_56.35.255a-b.jpg?width=900"),
    ("NOOR-NIGHT", "عطر ليالي", 1100, "عطر مسائي فاخر بنفحات خشبية عميقة.",
     "https://commons.wikimedia.org/wiki/Special:Redirect/file/Perfume_Bottle_And_Stopper%2C_ca._1915_%28CH_18454099-2%29.jpg?width=900"),
    ("NOOR-MUSK", "مسك ناعم", 640, "مسك نظيف وهادئ مناسب لكل الأوقات.",
     "https://commons.wikimedia.org/wiki/Special:Redirect/file/Glass_perfume_bottle_MET_DP204508.jpg?width=900"),
    ("NOOR-CLASSIC", "عطر كلاسيك", 780, "تركيبة كلاسيكية متوازنة وثابتة.",
     "https://commons.wikimedia.org/wiki/Special:Redirect/file/Tiffany_-_Perfume_bottle_and_two_jars.jpg?width=900"),
]


THEMES = [
    ("Dukkani Boutique", "دكاني بوتيك", "boutique", "#7c3aed", "#faf7ff", "#24123a"),
    ("Dukkani Minimal", "دكاني مينيمال", "minimal", "#111827", "#f8fafc", "#111827"),
    ("Dukkani Warm", "دكاني دافئ", "warm", "#b45309", "#fff7ed", "#431407"),
]


PAGE_DATA_SCRIPT = r'''
company = frappe.db.get_single_value("Global Defaults", "default_company") or "متجري"
currency = frappe.get_doc("Company", company).default_currency or "SAR"
products = []

def _item_images(item):
    images = []
    primary = item.image or ""
    if primary:
        images.append(primary)
    for row in frappe.get_all(
        "File",
        filters={"attached_to_doctype": "Item", "attached_to_name": item.name, "is_folder": 0},
        fields=["file_url"],
        order_by="creation asc",
        limit_page_length=20,
    ):
        url = row.file_url or ""
        if not url:
            continue
        if not url.lower().split("?", 1)[0].endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            continue
        if url not in images:
            images.append(url)
    return images

for item in frappe.db.get_all("Item", filters={"disabled": 0}, fields=["name", "item_name", "description", "image"], limit_page_length=100):
    prices = frappe.db.get_all("Item Price", filters={"item_code": item.name, "selling": 1}, fields=["price_list_rate"], limit_page_length=1)
    price = prices[0].price_list_rate if prices else 0
    images = _item_images(item)
    products.append({
        "code": item.name,
        "name": item.item_name,
        "description": (item.description or "")[:140],
        "image": images[0] if images else "https://placehold.co/800x800/f3f4f6/64748b?text=Product",
        "images": images,
        "display_price": f"{price:,.0f} {currency}",
    })
data.update({"store_name": company, "products": products})
'''

STOREFRONT_BODY_HTML = r'''
<script>
document.addEventListener("click", function (event) {
  const trigger = event.target.closest('a[href="#products"], a[href="/shop#products"]');
  if (!trigger) return;
  event.preventDefault();
  const products = document.getElementById("products");
  if (products) {
    products.scrollIntoView({ behavior: "smooth", block: "start" });
    history.replaceState(null, "", "#products");
  }
});
</script>
'''


def block(element="div", *, styles=None, mobile=None, attrs=None, text=None, children=None,
          name=None, original=None, repeater=False):
    return Block(
        blockId=frappe.generate_hash(length=9),
        element=element,
        blockName=name,
        originalElement=original,
        baseStyles=styles or {},
        mobileStyles=mobile or {},
        attributes=attrs or {},
        innerHTML=text,
        children=children or [],
        isRepeaterBlock=repeater,
    )


def dynamic_text(element, key, styles=None, fallback=""):
    node = block(element, styles=styles, text=fallback)
    node.set_dynamic_value(key, "key", "innerHTML")
    return node


def make_theme_blocks(accent, background, ink):
    store_name = dynamic_text("div", "store_name", {
        "fontSize": "22px", "fontWeight": "800", "color": ink,
    }, "متجري")
    nav = block("nav", styles={
        "alignItems": "center", "display": "flex", "justifyContent": "space-between",
        "paddingBottom": "20px", "paddingLeft": "5%", "paddingRight": "5%",
        "paddingTop": "20px", "width": "100%", "background": "#ffffff",
    }, children=[store_name])

    hero = block("section", styles={
        "alignItems": "center", "background": background, "display": "flex",
        "flexDirection": "column", "gap": "18px", "paddingBottom": "110px",
        "paddingLeft": "6%", "paddingRight": "6%", "paddingTop": "110px",
        "textAlign": "center", "width": "100%",
    }, children=[
        block("div", styles={"color": accent, "fontSize": "14px", "fontWeight": "700"}, text="تشكيلة مختارة بعناية"),
        block("h1", styles={"color": ink, "fontSize": "54px", "fontWeight": "800", "lineHeight": "120%", "maxWidth": "780px"},
              mobile={"fontSize": "36px"}, text="كل ما تحبينه، في مكان واحد"),
        block("p", styles={"color": "#64748b", "fontSize": "18px", "lineHeight": "170%", "maxWidth": "620px"},
              text="اكتشفي منتجات متجرنا واختاري ما يناسبك بسهولة."),
    ])

    image = block("img", attrs={"src": "https://placehold.co/800x800", "alt": "Product"}, styles={
        "aspectRatio": "1 / 1", "borderRadius": "18px", "objectFit": "cover", "width": "100%",
    })
    image.set_dynamic_value("image", "attribute", "src")
    add_to_cart = block("button", attrs={"type": "button"}, styles={
        "background": accent, "borderRadius": "12px", "borderWidth": "0px",
        "color": "#ffffff", "cursor": "pointer", "fontSize": "16px",
        "fontWeight": "700", "marginTop": "auto", "paddingBottom": "12px",
        "paddingLeft": "16px", "paddingRight": "16px", "paddingTop": "12px",
        "width": "100%",
    }, text="أضف للسلة", name="Add to cart")
    add_to_cart.set_dynamic_value("code", "attribute", "data-product-code")
    card = block("article", styles={
        "background": "#ffffff", "borderColor": "#e5e7eb", "borderRadius": "22px",
        "borderStyle": "solid", "borderWidth": "1px", "display": "flex",
        "flexDirection": "column", "gap": "12px", "paddingBottom": "16px",
        "paddingLeft": "16px", "paddingRight": "16px", "paddingTop": "16px",
    }, children=[
        image,
        dynamic_text("h3", "name", {"color": ink, "fontSize": "18px", "fontWeight": "750"}, "اسم المنتج"),
        dynamic_text("p", "description", {"color": "#64748b", "fontSize": "14px", "lineHeight": "160%"}, "وصف المنتج"),
        dynamic_text("div", "display_price", {"color": accent, "fontSize": "18px", "fontWeight": "800"}, "0 SAR"),
        add_to_cart,
    ])
    repeater = block("div", styles={
        "display": "grid", "gap": "22px", "gridTemplateColumns": "repeat(3, minmax(0, 1fr))", "width": "100%",
    }, mobile={"gridTemplateColumns": "repeat(1, minmax(0, 1fr))"}, children=[card], repeater=True)
    repeater.attach_data_key("products", "dataKey")

    products = block("section", attrs={"id": "products"}, styles={
        "background": "#ffffff", "display": "flex", "flexDirection": "column", "gap": "30px",
        "paddingBottom": "80px", "paddingLeft": "6%", "paddingRight": "6%", "paddingTop": "80px", "width": "100%",
    }, children=[
        block("h2", styles={"color": ink, "fontSize": "34px", "fontWeight": "800", "textAlign": "center"}, text="منتجاتنا"),
        repeater,
    ])
    footer = block("footer", styles={
        "background": ink, "color": "#ffffff", "paddingBottom": "30px", "paddingTop": "30px",
        "textAlign": "center", "width": "100%",
    }, text="صُنع بكل حب على منصة دكاني")
    return block("div", original="body", attrs={"dir": "rtl", "lang": "ar"}, styles={
        "background": "#ffffff", "fontFamily": "Tajawal, Arial, sans-serif", "margin": "0px", "width": "100%",
    }, children=[nav, hero, products, footer]).as_json(wrap_in_array=True)


def ensure_owner_builder_role():
    if not OWNER_EMAIL or not frappe.db.exists("User", OWNER_EMAIL):
        return
    if not frappe.db.exists("Has Role", {"parent": OWNER_EMAIL, "role": "Website Manager"}):
        frappe.get_doc({
            "doctype": "Has Role", "parent": OWNER_EMAIL, "parenttype": "User",
            "parentfield": "roles", "role": "Website Manager",
        }).insert(ignore_permissions=True)


def ensure_builder_icon():
    # Builder v1 creates its own standard "Frappe Builder" desktop icon on
    # migrate. Prefer it and remove the older Dukkani fallback to avoid twins.
    if frappe.db.exists("Desktop Icon", "Frappe Builder"):
        if frappe.db.exists("Desktop Icon", "Builder"):
            frappe.delete_doc("Desktop Icon", "Builder", force=True, ignore_permissions=True)
        frappe.db.set_value("Desktop Icon", "Frappe Builder", {
            "hidden": 0,
            "label": "Builder",
        })
        return
    values = {
        "label": "Builder", "icon_type": "App", "link_type": "External",
        "app": "builder", "logo_url": "/assets/builder/frontend/builder_logo.png",
        "link": "/builder", "hidden": 0,
    }
    if frappe.db.exists("Desktop Icon", "Builder"):
        frappe.db.set_value("Desktop Icon", "Builder", values)
    else:
        frappe.get_doc({"doctype": "Desktop Icon", "name": "Builder", **values}).insert(ignore_permissions=True)


def ensure_shop_icon():
    """Give every merchant a one-click shortcut to their public storefront."""
    values = {
        "label": "\u0648\u0627\u062c\u0647\u0629 \u0627\u0644\u0645\u062a\u062c\u0631",
        "icon_type": "App",
        "link_type": "External",
        "app": "erpnext",
        "logo_url": "/assets/erpnext/images/erpnext-logo.svg",
        "link": "/",
        "hidden": 0,
        "idx": 90,
    }
    name = (
        frappe.db.get_value("Desktop Icon", {"link": "/shop"}, "name")
        or frappe.db.get_value("Desktop Icon", {"label": ["in", ["متجري", "واجهة المتجر", "المتجر الإلكتروني"]]}, "name")
    )
    if name:
        frappe.db.set_value("Desktop Icon", name, values)
    else:
        frappe.get_doc({"doctype": "Desktop Icon", **values}).insert(ignore_permissions=True)


def ensure_desktop_icon_order():
    """Keep the merchant app grid deterministic across every tenant."""
    ordered_icons = [
        "Framework",
        "Organization",
        "Accounting",
        "Buying",
        "Selling",
        "Stock",
        "ERPNext Settings",
    ]
    for position, icon_name in enumerate(ordered_icons, start=1):
        if frappe.db.exists("Desktop Icon", icon_name):
            frappe.db.set_value("Desktop Icon", icon_name, "idx", position * 10)

    builder_name = "Frappe Builder" if frappe.db.exists("Desktop Icon", "Frappe Builder") else "Builder"
    if frappe.db.exists("Desktop Icon", builder_name):
        frappe.db.set_value("Desktop Icon", builder_name, "idx", 80)
    shop_icon = frappe.db.get_value("Desktop Icon", {"label": ["in", ["متجري", "واجهة المتجر", "المتجر الإلكتروني"]]}, "name")
    if shop_icon:
        frappe.db.set_value("Desktop Icon", shop_icon, "idx", 90)


def ensure_demo_products():
    if not SEED_DEMO_PRODUCTS:
        return
    item_group = "Dukkani Products" if frappe.db.exists("Item Group", "Dukkani Products") else "Products"
    price_list = frappe.db.get_value("Price List", {"selling": 1}, "name") or "Standard Selling"
    currency = frappe.db.get_value("Price List", price_list, "currency") or "EGP"
    for code, name, price, description, image in DEMO_PRODUCTS:
        if not frappe.db.exists("Item", code):
            frappe.get_doc({
                "doctype": "Item", "item_code": code, "item_name": name,
                "item_group": item_group, "stock_uom": "Nos", "is_stock_item": 0,
                "description": description, "image": image,
            }).insert(ignore_permissions=True)
        else:
            frappe.db.set_value("Item", code, {"item_name": name, "description": description, "image": image, "disabled": 0})
        price_name = frappe.db.get_value("Item Price", {"item_code": code, "price_list": price_list})
        if price_name:
            frappe.db.set_value("Item Price", price_name, "price_list_rate", price)
        else:
            frappe.get_doc({
                "doctype": "Item Price", "item_code": code, "price_list": price_list,
                "price_list_rate": price, "currency": currency, "selling": 1,
            }).insert(ignore_permissions=True)


def ensure_storefront_script():
    """Install the shared cart/checkout behaviour used by every visual theme."""
    if not os.path.exists(STOREFRONT_CART_PATH):
        frappe.throw(f"Missing storefront commerce script: {STOREFRONT_CART_PATH}")
    with open(STOREFRONT_CART_PATH, encoding="utf-8") as source:
        script = source.read()
    if frappe.db.exists("Builder Client Script", STOREFRONT_SCRIPT_NAME):
        doc = frappe.get_doc("Builder Client Script", STOREFRONT_SCRIPT_NAME)
        doc.script_type = "JavaScript"
        doc.script = script
        doc.save(ignore_permissions=True)
    else:
        doc = frappe.get_doc({
            "doctype": "Builder Client Script", "name": STOREFRONT_SCRIPT_NAME,
            "script_type": "JavaScript", "script": script,
        }).insert(ignore_permissions=True)
    return doc.name


def ensure_customer_signup_link():
    marker = "DUKKANI_CUSTOMER_SIGNUP_LINK"
    script = r'''
// DUKKANI_CUSTOMER_SIGNUP_LINK
(() => {
  const connectCustomerSignup = () => {
    if (document.querySelector("section.for-login")) return;
    const link = document.querySelector('.sign-up-message a[href="#signup"]');
    if (link) link.href = "/customer-signup";
  };
  connectCustomerSignup();
  document.addEventListener("DOMContentLoaded", connectCustomerSignup);
  window.addEventListener("hashchange", connectCustomerSignup);
})();
'''
    website_script = frappe.get_single("Website Script")
    javascript = website_script.javascript or ""
    if marker not in javascript:
        website_script.javascript = javascript.rstrip() + "\n" + script
        website_script.save(ignore_permissions=True)


def ensure_themes(storefront_script):
    for name, title, slug, accent, background, ink in THEMES:
        values = {
            "page_name": title, "page_title": title, "route": f"themes/{slug}",
            # Keep starters as normal draft pages. Builder's current template gallery
            # only reads from an external Hub, while local draft pages remain fully
            # editable and can be previewed/published by the merchant.
            "published": 0, "is_template": 0, "template_group": None,
            "language": "ar", "page_data_script": PAGE_DATA_SCRIPT,
            "body_html": "",
            "blocks": make_theme_blocks(accent, background, ink),
        }
        # Builder replaces page_name with the generated document name, so route
        # is the stable idempotency key for starter pages.
        routes = [f"themes/{slug}"]
        # Once Boutique is chosen for the live store its route becomes /shop;
        # keep treating that published page as the Boutique theme instead of
        # creating a duplicate card in Builder.
        if slug == "boutique":
            routes.append("shop")
        existing_pages = frappe.get_all(
            "Builder Page", filters={"route": ["in", routes]},
            fields=["name"], order_by="modified desc",
        )
        existing = existing_pages[0].name if existing_pages else None
        if existing:
            doc = frappe.get_doc("Builder Page", existing)
            # Re-running tenant setup must not undo a merchant's publish choice.
            values["published"] = doc.published
            if doc.route == "shop":
                values["route"] = "shop"
            doc.update(values)
            if not any(row.builder_script == storefront_script for row in doc.client_scripts):
                doc.append("client_scripts", {"builder_script": storefront_script})
            doc.save(ignore_permissions=True)
            for duplicate in existing_pages[1:]:
                frappe.delete_doc("Builder Page", duplicate.name, force=True, ignore_permissions=True)
        else:
            doc = frappe.get_doc({"doctype": "Builder Page", **values})
            doc.append("client_scripts", {"builder_script": storefront_script})
            doc.insert(ignore_permissions=True)


def apply_storefront_starter():
    ensure_owner_builder_role()
    ensure_builder_icon()
    ensure_shop_icon()
    ensure_desktop_icon_order()
    ensure_demo_products()
    storefront_script = ensure_storefront_script()
    ensure_customer_signup_link()
    ensure_themes(storefront_script)
    website_settings = frappe.get_single("Website Settings")
    website_settings.home_page = "shop"
    website_settings.disable_signup = 0
    website_settings.save(ignore_permissions=True)
    app_row = frappe.db.get_value("Installed Application", {"app_name": "builder"})
    if app_row:
        frappe.db.set_value("Installed Application", app_row, "is_setup_complete", 1)
    frappe.db.commit()
    frappe.clear_cache()
    print("Dukkani storefront starter ready: 3 themes" + (" + demo products" if SEED_DEMO_PRODUCTS else ""))


apply_storefront_starter()
