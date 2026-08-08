(function () {
  // Store API routes are reverse-proxied on the current tenant host.
  const API = "";
  const STORE = location.hostname.split(".")[0];
  let products = [];
  let activeSenseCategory = "all";
  let storeCurrency = "SAR";
  const CART_KEY = `dukkani-cart-${STORE}`;
  const LEGACY_CUSTOMER_KEY = `dukkani-customer-${STORE}`;
  const CUSTOMER_KEY = `dukkani-customer-v2-${STORE}`;
  const CHECKOUT_DRAFT_KEY = `dukkani-checkout-draft-${STORE}`;
  const PRODUCT_ATTEMPTS = 2;
  const PRODUCT_TIMEOUT_MS = 8000;
  let cart = {};
  // v1 could treat an ERPNext merchant as a storefront customer. Never reuse
  // that identity after the merchant/customer separation was introduced.
  localStorage.removeItem(LEGACY_CUSTOMER_KEY);
  try {
    const savedCart = JSON.parse(localStorage.getItem(CART_KEY) || "{}");
    if (savedCart && typeof savedCart === "object" && !Array.isArray(savedCart)) cart = savedCart;
  } catch (error) {
    localStorage.removeItem(CART_KEY);
    console.warn("Dukkani cart: discarded invalid saved cart", error);
  }
  const locationData = { lat: null, lng: null };

  const money = value => (Number(value) || 0).toLocaleString("ar-EG");
  const save = () => {
    try { localStorage.setItem(CART_KEY, JSON.stringify(cart)); }
    catch (error) { console.warn("Dukkani cart: could not save cart", error); }
  };
  const count = () => Object.values(cart).reduce((sum, row) => sum + row.qty, 0);
  const total = () => Object.values(cart).reduce((sum, row) => sum + row.qty * row.rate, 0);

  function findCustomerLoginBadge() {
    return Array.from(document.querySelectorAll("nav *")).find(element =>
      element.children.length === 0 && element.textContent.trim() === "\u062f\u062e\u0648\u0644"
    );
  }

  function currentCustomer() {
    try {
      const customer = JSON.parse(localStorage.getItem(CUSTOMER_KEY) || "null");
      return customer && customer.loggedIn && customer.email ? customer : null;
    } catch (error) {
      localStorage.removeItem(CUSTOMER_KEY);
      return null;
    }
  }

  function currentUser() {
    const customer = currentCustomer();
    return customer ? customer.email : "Guest";
  }

  function customerIsLoggedIn() {
    const user = currentUser();
    return Boolean(user && user !== "Guest");
  }

  function installCustomerAccount() {
    const badge = findCustomerLoginBadge();
    const nav = document.querySelector("nav");
    if (!badge && !nav) return;
    const link = document.createElement("a");
    link.className = badge ? badge.className : "dukkani-customer-access";
    link.style.textDecoration = "none";
    link.style.marginInlineStart = "auto";
    link.style.color = "inherit";
    link.style.fontWeight = "700";
    link.setAttribute("rel", "nofollow");
    link.textContent = "\u062f\u062e\u0648\u0644";
    link.href = "/customer-login";
    if (badge) badge.replaceWith(link);
    else nav.appendChild(link);
    const user = currentUser();
    if (user && user !== "Guest") {
      link.textContent = "\u062d\u0633\u0627\u0628\u064a";
      link.href = "/customer-account";
    }
    link.addEventListener("click", event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      location.assign(customerIsLoggedIn() ? "/customer-account" : "/customer-login");
    });
  }

  function installSenseHeader() {
    if (STORE !== "sense" || document.querySelector(".sense-store-nav")) return;
    const candidates = Array.from(document.querySelectorAll("nav, header, section, div"));
    const nav = candidates.find(element => {
      const text = element.textContent.replace(/\s+/g, " ").trim();
      return element.querySelector("img") && text.includes("الأقسام") && text.includes("المنتجات");
    }) || document.querySelector("nav, header");
    if (!nav) return;
    nav.className = "sense-store-nav";
    nav.removeAttribute("style");
    nav.innerHTML = `
      <div class="sense-store-nav-top">
        <a class="sense-store-account" href="/customer-account">حسابي</a>
        <form class="sense-store-search" action="/#products" role="search">
          <button type="submit" aria-label="بحث">
            <svg viewBox="0 0 24 24" fill="none" stroke-width="2.2" aria-hidden="true">
              <circle cx="11" cy="11" r="7"></circle>
              <path d="m16.5 16.5 4 4"></path>
            </svg>
          </button>
          <input type="search" name="q" placeholder="أنا أبحث عن..." aria-label="بحث عن منتج">
        </form>
        <a class="sense-store-logo" href="/" aria-label="Sense home">
          <img src="/files/sense-brand-logo.png" alt="SenSe">
        </a>
      </div>
      <div class="sense-store-links" aria-label="روابط المتجر">
        <a href="#categories">كل الأقسام</a>
        <a href="#brands">كل العلامات التجارية</a>
        <a href="/blog">المدونة</a>
      </div>
    `;
    const search = nav.querySelector(".sense-store-search");
    search.addEventListener("submit", event => {
      event.preventDefault();
      const term = nav.querySelector("input[name='q']").value.trim().toLowerCase();
      const target = document.getElementById("products");
      if (target) target.scrollIntoView({ block: "start", behavior: "smooth" });
      if (!term) return;
      const match = products.find(product =>
        [product.name, product.code, product.description].some(value => String(value || "").toLowerCase().includes(term))
      );
      if (match) openProductDetail(match.code);
    });
  }

  function syncThemeColors() {
    const themeButton = document.querySelector("#products [data-product-code], #products .dukkani-add");
    if (!themeButton) return;
    const style = getComputedStyle(themeButton);
    document.documentElement.style.setProperty("--dukkani-accent", style.backgroundColor);
    document.documentElement.style.setProperty("--dukkani-accent-ink", style.color);
  }

  function installUI() {
    if (document.getElementById("dukkani-cart-overlay")) return;
    const headerCartButton = document.getElementById("dukkani-header-cart-button");
    document.head.insertAdjacentHTML("beforeend", `<style>
      :root{--dukkani-accent:#7c3aed;--dukkani-accent-ink:#fff}
      .dukkani-add{cursor:pointer}
      #dukkani-cart-button{position:fixed;left:24px;bottom:24px;z-index:9998;border:0;border-radius:999px;padding:14px 20px;background:var(--dukkani-accent);color:var(--dukkani-accent-ink);font:700 16px Arial;cursor:pointer;box-shadow:0 8px 30px #0003}
      #dukkani-track-link{position:fixed;left:24px;bottom:24px;z-index:9998;border:1px solid var(--dukkani-accent);border-radius:999px;padding:11px 18px;background:var(--dukkani-accent);color:var(--dukkani-accent-ink);font:800 14px Tajawal,Arial,sans-serif;text-decoration:none;box-shadow:0 6px 22px #0002;opacity:1;visibility:visible}
      #dukkani-cart-count{display:inline-flex;min-width:24px;height:24px;align-items:center;justify-content:center;border-radius:99px;background:#ef4444;margin-right:7px}
      #dukkani-cart-overlay{position:fixed;inset:0;background:#0007;z-index:9999;display:none}
      #dukkani-cart-overlay.open{display:block}
      #dukkani-cart-panel{position:absolute;left:0;top:0;height:100%;width:min(440px,94vw);overflow:auto;background:#fff;padding:24px;direction:rtl;font-family:Tajawal,Arial,sans-serif}
      .dukkani-cart-head{display:flex;justify-content:space-between;align-items:center}.dukkani-close{border:0;background:none;font-size:28px;cursor:pointer}
      .dukkani-product-carousel{position:relative;display:block;overflow:hidden;border-radius:inherit;background:#f8fafc}
      .dukkani-product-carousel img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .55s ease}
      .dukkani-product-carousel img.active{opacity:1}
      .dukkani-product-dots{position:absolute;left:10px;right:10px;bottom:9px;display:flex;gap:6px;justify-content:center;pointer-events:none}
      .dukkani-product-dots span{width:7px;height:7px;border-radius:999px;background:#fff8;border:1px solid #0002}
      .dukkani-product-dots span.active{background:#fff}
      .dukkani-product-clickable{cursor:pointer}
      .dukkani-product-clickable:hover{transform:translateY(-2px);transition:transform .2s ease}
      #dukkani-product-detail-page{background:#f4f5f7;color:#1f2933;direction:rtl;font-family:Cairo,Tajawal,Arial,sans-serif;min-height:100vh;padding:0 0 80px}
      body.dukkani-detail-open>*:not(#dukkani-product-detail-page):not(#dukkani-cart-overlay):not(#dukkani-cart-button):not(#dukkani-header-cart-button):not(.sense-whatsapp){display:none!important}
      .dukkani-detail-top{background:#fff;border-bottom:1px solid #e5e7eb;box-shadow:0 2px 12px #00000008}
      .dukkani-detail-top-inner{align-items:center;display:grid;grid-template-columns:auto minmax(260px,1fr) auto;gap:22px;margin:0 auto;max-width:1240px;padding:18px 24px}
      .dukkani-detail-logo{align-items:center;display:flex;gap:10px;text-decoration:none;color:#1f2933;font-weight:900}.dukkani-detail-logo-mark{align-items:center;background:#f54873;border-radius:12px;color:#fff;display:inline-flex;font-size:26px;height:48px;justify-content:center;width:48px}.dukkani-detail-logo-text{color:#f54873;font-size:27px;font-weight:900;line-height:1}.dukkani-detail-logo-sub{color:#1f2933;font-size:13px;margin-top:2px}
      .dukkani-detail-back{background:#111827;border:0;border-radius:4px;color:#fff;cursor:pointer;font:900 14px Tajawal,Arial,sans-serif;padding:12px 20px;text-transform:uppercase}
      .dukkani-detail-search{display:flex;direction:rtl}.dukkani-detail-search input{background:#f7f8fa;border:1px solid #e5e7eb;border-radius:4px 0 0 4px;color:#333;font:600 14px Tajawal,Arial,sans-serif;height:44px;min-width:0;padding:0 14px;width:100%}.dukkani-detail-search button{background:#ef4d6e;border:0;border-radius:0 4px 4px 0;color:#fff;font-weight:900;min-width:52px}
      .dukkani-detail-header-actions{align-items:center;display:flex;gap:16px;justify-content:flex-end}.dukkani-detail-header-actions a,.dukkani-detail-header-actions button{align-items:center;background:#fff;border:0;color:#333;cursor:pointer;display:flex;flex-direction:column;font:700 12px Tajawal,Arial,sans-serif;gap:3px;text-decoration:none}.dukkani-detail-header-actions b{align-items:center;background:#ef4d6e;border-radius:999px;color:#fff;display:inline-flex;font-size:11px;height:20px;justify-content:center;min-width:20px}
      .dukkani-detail-nav{background:#111827}.dukkani-detail-nav-inner{align-items:center;display:flex;gap:28px;margin:0 auto;max-width:1240px;padding:12px 24px}.dukkani-detail-nav a{color:#fff;font:800 14px Tajawal,Arial,sans-serif;text-decoration:none}.dukkani-detail-nav a:first-child{background:#ef4d6e;border-radius:4px;padding:8px 14px}
      .dukkani-detail-wrap{max-width:1240px;margin:0 auto;padding:22px 24px 0}
      .dukkani-detail-breadcrumb{color:#71717a;font-size:14px;margin:0 0 18px}.dukkani-detail-breadcrumb a{color:#71717a;text-decoration:none}.dukkani-detail-breadcrumb strong{color:#111827}
      .dukkani-detail-card{background:#fff;border:1px solid #e5e7eb;border-radius:4px;box-shadow:0 10px 30px #0000000a;padding:22px}
      .dukkani-detail-grid{display:grid;grid-template-columns:minmax(320px,520px) 1fr;gap:34px;align-items:start;direction:ltr}
      .dukkani-detail-gallery{display:grid;gap:14px;direction:rtl}.dukkani-detail-main-image{align-items:center;aspect-ratio:1/1;background:#fff;border:1px solid #eeeeee;display:flex;justify-content:center;overflow:hidden;padding:18px}.dukkani-detail-main-image img{height:100%;object-fit:contain;width:100%}
      .dukkani-detail-thumbs{display:flex;gap:10px;flex-wrap:wrap}.dukkani-detail-thumbs button{background:#fff;border:1px solid #e5e7eb;border-radius:4px;cursor:pointer;height:76px;overflow:hidden;padding:6px;width:76px}.dukkani-detail-thumbs button.active{border-color:#f54873;box-shadow:0 0 0 2px #f5487326}.dukkani-detail-thumbs img{height:100%;object-fit:contain;width:100%}
      .dukkani-detail-info{direction:rtl;text-align:right}.dukkani-detail-info h1{color:#222;font-size:28px;font-weight:800;line-height:1.45;margin:0 0 12px}.dukkani-detail-rating{align-items:center;color:#f6b100;display:flex;gap:8px;font-size:15px;justify-content:flex-start;margin-bottom:14px}.dukkani-detail-rating span{color:#858585;font-size:13px}
      .dukkani-detail-meta{border-bottom:1px solid #eeeeee;border-top:1px solid #eeeeee;color:#777;display:grid;gap:8px;font-size:14px;margin:0 0 18px;padding:14px 0}.dukkani-detail-meta b{color:#333}.dukkani-detail-code{direction:ltr;display:inline-block}
      .dukkani-detail-price{color:#e62e4d;font-size:31px;font-weight:900;margin:0 0 18px}.dukkani-detail-stock{border-radius:3px;display:inline-block;font-weight:800;margin-bottom:18px;padding:7px 12px}.dukkani-detail-stock.in{background:#e7f8ef;color:#15945c}.dukkani-detail-stock.out{background:#fee2e2;color:#b91c1c}
      .dukkani-detail-short{color:#555;font-size:16px;line-height:1.9;margin:0 0 18px}.dukkani-detail-actions{align-items:center;display:flex;flex-wrap:wrap;gap:12px;margin:18px 0}.dukkani-detail-qty{align-items:center;border:1px solid #e5e7eb;display:inline-flex;height:46px}.dukkani-detail-qty button{background:#f8f8f8;border:0;color:#555;cursor:pointer;font-size:20px;height:44px;width:42px}.dukkani-detail-qty strong{color:#111;display:inline-flex;justify-content:center;min-width:44px}
      .dukkani-detail-add,.dukkani-detail-buy{border:0;border-radius:3px;color:#fff;cursor:pointer;font:900 15px Tajawal,Arial,sans-serif;min-width:160px;padding:14px 22px}.dukkani-detail-add{background:#f54873}.dukkani-detail-buy{background:#111827}.dukkani-detail-add:disabled,.dukkani-detail-buy:disabled{cursor:not-allowed;opacity:.55}.dukkani-detail-mini-actions{display:flex;gap:10px;margin-top:12px}.dukkani-detail-mini-actions button,.dukkani-detail-mini-actions a{align-items:center;background:#fff;border:1px solid #e5e7eb;border-radius:4px;color:#666;display:inline-flex;height:40px;justify-content:center;text-decoration:none;width:40px}
      .dukkani-detail-tabs{background:#fff;border:1px solid #e5e7eb;border-radius:4px;margin-top:24px}.dukkani-detail-tabs h2{border-bottom:1px solid #eee;color:#222;font-size:20px;margin:0;padding:18px 22px}.dukkani-detail-desc{color:#555;font-size:16px;line-height:2;padding:20px 22px}.dukkani-detail-reviews{border-top:1px solid #eeeeee;margin:0;padding:20px 22px}.dukkani-detail-reviews h2{border:0;font-size:19px;margin:0 0 14px;padding:0}.dukkani-review{background:#fafafa;border:1px solid #eeeeee;border-radius:4px;margin-bottom:10px;padding:14px}.dukkani-review-stars{color:#f59e0b;font-weight:900}
      .dukkani-related{margin-top:28px}.dukkani-related h2{color:#222;font-size:22px;margin:0 0 16px}.dukkani-related-grid{display:grid;gap:18px;grid-template-columns:repeat(4,minmax(0,1fr))}.dukkani-related-card{background:#fff;border:1px solid #e5e7eb;border-radius:4px;color:#222;cursor:pointer;padding:14px;text-align:center}.dukkani-related-card img{aspect-ratio:1/1;object-fit:contain;width:100%}.dukkani-related-card h3{font-size:14px;line-height:1.6;margin:10px 0 8px}.dukkani-related-card strong{color:#e62e4d}
      @media(max-width:900px){.dukkani-detail-top-inner{grid-template-columns:1fr;justify-items:center;padding-left:16px;padding-right:16px}.dukkani-detail-wrap{padding-left:16px;padding-right:16px}.dukkani-detail-search{width:100%}.dukkani-detail-nav-inner{flex-wrap:wrap;gap:12px;justify-content:center}.dukkani-detail-grid{grid-template-columns:1fr;direction:rtl}.dukkani-detail-info h1{font-size:23px}.dukkani-detail-actions{align-items:stretch;flex-direction:column}.dukkani-detail-add,.dukkani-detail-buy{width:100%}.dukkani-related-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
      .sense-categories{direction:rtl;background:#151817;color:#fff;font-family:Tajawal,Arial,sans-serif;padding:64px 6% 72px;text-align:center}.sense-categories h2{font-size:38px;font-weight:900;margin:0 0 14px}.sense-categories p{color:#d8d0c4;font-size:18px;margin:0 0 34px}.sense-category-grid{display:grid;gap:18px;grid-template-columns:repeat(6,minmax(0,1fr));margin:0 auto;max-width:1260px}.sense-category-card{align-items:center;background:#1e2221;border:1px solid #333836;border-radius:18px;color:#fff;display:flex;flex-direction:column;font-size:18px;font-weight:900;gap:12px;min-height:130px;justify-content:center;text-decoration:none;transition:transform .2s ease,border-color .2s ease}.sense-category-card:hover{border-color:#f54873;transform:translateY(-3px)}.sense-category-icon{align-items:center;background:#b40e35;border-radius:999px;display:inline-flex;font-size:28px;height:58px;justify-content:center;width:58px}@media(max-width:1100px){.sense-category-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:640px){.sense-category-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.sense-categories h2{font-size:30px}}
      .dukkani-hero-carousel{position:relative;display:block;overflow:hidden;border-radius:inherit;direction:ltr}
      .dukkani-hero-track{display:flex;flex-direction:row-reverse;direction:ltr;width:100%;height:100%;transition:transform .65s ease;will-change:transform}
      .dukkani-hero-track img{flex:0 0 100%;width:100%;height:100%;object-fit:cover;display:block}
      .dukkani-hero-dots{position:absolute;left:16px;right:16px;bottom:14px;display:flex;gap:7px;justify-content:center;pointer-events:none;z-index:2}
      .dukkani-hero-dots span{width:8px;height:8px;border-radius:999px;background:#fff8;border:1px solid #0002}
      .dukkani-hero-dots span.active{background:#fff}
      .sense-store-nav{background:#151817!important;border-top:3px solid #b40e35;border-bottom:1px solid #2e3331;color:#f4eee6!important;direction:ltr!important;display:block!important;font-family:Tajawal,Arial,sans-serif!important;padding:8px 2.2% 0!important;width:100%!important}
      .sense-store-nav-top{align-items:center;display:grid;gap:20px;grid-template-columns:auto minmax(260px,1fr) minmax(180px,auto);margin:0 auto;max-width:1580px;min-height:56px}
      .sense-store-account{color:#f4eee6;font:900 16px Tajawal,Arial,sans-serif;justify-self:start;text-decoration:none;white-space:nowrap}.sense-store-account:hover{color:#f54873}
      .sense-store-search{display:flex;min-width:0;width:100%}.sense-store-search button{align-items:center;background:#b40e35;border:0;color:#fff;cursor:pointer;display:flex;height:46px;justify-content:center;width:48px}.sense-store-search svg{height:23px;width:23px;stroke:currentColor}.sense-store-search input{background:#151817;border:1px solid #454a48;border-left:0;color:#f4eee6;direction:rtl;flex:1;font:500 16px Tajawal,Arial,sans-serif;height:46px;min-width:0;padding:0 16px;text-align:right}.sense-store-search input::placeholder{color:#b23a54;opacity:.9}
      .sense-store-logo{align-items:center;display:flex;gap:8px;justify-self:end;min-width:180px}.sense-store-logo img{display:block;max-height:48px;max-width:190px;object-fit:contain}
      .sense-store-links{align-items:center;display:flex;gap:28px;justify-content:flex-end;margin:0 auto;max-width:1580px;padding:12px 0 14px}.sense-store-links a{color:#f4eee6;font:900 16px Tajawal,Arial,sans-serif;text-decoration:none}.sense-store-links a:nth-child(n+2){color:#f54873}.sense-store-links a:hover{color:#fff}
      @media(max-width:760px){.sense-store-nav{padding-left:14px!important;padding-right:14px!important}.sense-store-nav-top{gap:14px;grid-template-columns:1fr;min-height:0;padding:8px 0}.sense-store-logo{justify-self:center;order:-1}.sense-store-account{justify-self:center;order:3}.sense-store-search button{height:52px;width:54px}.sense-store-search input{height:52px;font-size:16px}.sense-store-links{flex-wrap:wrap;gap:18px;justify-content:center;padding:20px 0 22px}.sense-store-links a{font-size:16px}}
      .sense-footer{direction:rtl;background:#151817;color:#d8d0c4;font-family:Tajawal,Arial,sans-serif;margin-top:0;padding:52px 6% 0;width:100%}
      .sense-footer-grid{display:grid;grid-template-columns:1.3fr 1fr 1fr 1fr 1fr;gap:34px;align-items:start;max-width:1360px;margin:0 auto}
      .sense-footer-brand{text-align:right}.sense-footer-logo{max-width:190px;margin-bottom:18px}.sense-footer-brand p{font-size:18px;line-height:1.9;margin:0 0 20px;color:#f3efe8}
      .sense-footer-newsletter{display:flex;gap:0;max-width:310px;margin-inline-start:auto}.sense-footer-newsletter input{background:#181c1b;border:1px solid #3b3f3d;border-radius:6px 0 0 6px;color:#fff;direction:ltr;min-width:0;padding:14px;width:100%}.sense-footer-newsletter button,.sense-footer-seller a:first-child{background:#b40e35;border:0;border-radius:4px;color:#fff;font-weight:800;padding:14px 22px;text-decoration:none}
      .sense-footer-seller{align-items:center;display:flex;gap:12px;justify-content:flex-start;margin-top:26px}.sense-footer-seller span{color:#fff;font-size:18px;text-transform:uppercase}
      .sense-footer-col{text-align:center}.sense-footer-col h3{color:#f4eee6;font-size:16px;font-weight:900;margin:0 0 22px;text-transform:uppercase}.sense-footer-col h3:after{background:#c10f39;content:"";display:block;height:3px;margin:12px auto 0;width:76px}
      .sense-footer-col a,.sense-footer-col p{color:#8f8b84;display:block;font-size:16px;line-height:1.9;margin:0 0 8px;text-decoration:none}.sense-footer-col b{color:#aaa39a;display:block;font-weight:700;margin-top:8px}
      .sense-footer-app-icon{align-items:center;background:linear-gradient(135deg,#31489c,#25b69b);border:7px solid #f1f1f1;border-radius:999px;color:#fff;display:inline-flex;font-size:42px;font-weight:900;height:116px;justify-content:center;margin-top:6px;width:116px}
      .sense-footer-bottom{background:#1c201f;margin:48px -6% 0;padding:18px 6%}.sense-footer-bottom-inner{align-items:center;display:flex;gap:24px;justify-content:space-between;max-width:1360px;margin:0 auto}.sense-footer-payments,.sense-footer-social{align-items:center;display:flex;gap:14px}.sense-footer-payment{background:#232826;border-radius:8px;color:#ddd;font-size:13px;font-weight:800;padding:8px 12px}.sense-footer-social a{align-items:center;border-radius:999px;color:#fff;display:inline-flex;font-weight:900;height:42px;justify-content:center;text-decoration:none;width:42px}.sense-footer-social a:nth-child(1){background:#c13584}.sense-footer-social a:nth-child(2){background:#1da1f2}.sense-footer-social a:nth-child(3){background:#31569c}.sense-footer-copy{color:#8f8b84;font-size:14px;text-align:center}.sense-footer-detail{margin-top:48px}
      .sense-whatsapp{align-items:center;background:#0b8f45;border-radius:999px;bottom:150px;box-shadow:0 10px 28px #0004;color:#fff;display:flex;height:64px;justify-content:center;left:24px;position:fixed;text-decoration:none;width:64px;z-index:9998}
      .sense-whatsapp svg{display:block;height:34px;width:34px;fill:currentColor}
      @media(max-width:900px){.sense-footer-grid{grid-template-columns:1fr;text-align:center}.sense-footer-brand{text-align:center}.sense-footer-newsletter{margin:0 auto}.sense-footer-seller{justify-content:center}.sense-footer-bottom-inner{flex-direction:column}.sense-whatsapp{bottom:136px;height:56px;width:56px}.sense-whatsapp svg{height:30px;width:30px}}
      .dukkani-row{display:grid;grid-template-columns:1fr auto;gap:8px;border-bottom:1px solid #eee;padding:14px 0}.dukkani-qty{display:flex;gap:9px;align-items:center}.dukkani-qty button{width:30px;height:30px;border:1px solid #ddd;background:#fff;border-radius:8px;cursor:pointer}
      .dukkani-total{display:flex;justify-content:space-between;font-weight:800;font-size:19px;margin:20px 0}.dukkani-form label{display:block;font-weight:700;margin:5px 2px}.dukkani-form input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #ddd;border-radius:9px;margin:5px 0 11px;font:inherit}.dukkani-location{display:block!important;width:100%;padding:11px;border:1px solid #7c3aed!important;color:#7c3aed!important;-webkit-text-fill-color:#7c3aed!important;background:#fff!important;border-radius:9px;font:800 14px Tajawal,Arial,sans-serif!important;cursor:pointer;margin-bottom:8px;opacity:1!important;visibility:visible!important}.dukkani-location-note{font-size:13px;color:#15803d;margin-bottom:12px}.dukkani-payment{border:1px solid #ddd;border-radius:10px;padding:12px;margin:7px 0 14px}.dukkani-payment label{display:flex;gap:8px;align-items:center;margin:0}.dukkani-payment input{width:auto;margin:0}.dukkani-checkout{width:100%;border:0;border-radius:12px;padding:13px;background:var(--dukkani-accent);color:var(--dukkani-accent-ink);font:700 16px inherit;cursor:pointer}.dukkani-msg{padding:10px 0;color:#b91c1c}.dukkani-empty{text-align:center;color:#777;padding:35px 0}
    </style>`);
    document.body.insertAdjacentHTML("beforeend", `
      <a href="/track-order" id="dukkani-track-link">تتبع طلبك</a>
      ${headerCartButton ? "" : '<button id="dukkani-cart-button">🛒 السلة <span id="dukkani-cart-count">0</span></button>'}
      <div id="dukkani-cart-overlay"><aside id="dukkani-cart-panel">
        <div class="dukkani-cart-head"><h2>سلة المشتريات</h2><button class="dukkani-close" aria-label="إغلاق">×</button></div>
        <div id="dukkani-cart-items"></div><div id="dukkani-cart-footer"></div>
      </aside></div>`);
    const cartButton = headerCartButton || document.getElementById("dukkani-cart-button");
    if (!headerCartButton) document.getElementById("dukkani-track-link").style.bottom = "82px";
    if (cartButton && !headerCartButton) cartButton.onclick = openCart;
    document.querySelector(".dukkani-close").onclick = closeCart;
    document.getElementById("dukkani-cart-overlay").addEventListener("click", e => { if (e.target.id === "dukkani-cart-overlay") closeCart(); });
    updateCount();
  }

  function add(code) {
    const product = products.find(row => row.code === code);
    if (!product) return;
    cart[code] = cart[code] || { name: product.name, rate: Number(product.rate) || 0, qty: 0 };
    cart[code].qty += 1; save(); updateCount();
    const button = document.getElementById("dukkani-header-cart-button") || document.getElementById("dukkani-cart-button");
    if (button && typeof button.animate === "function") {
      button.animate([{transform:"scale(1)"},{transform:"scale(1.12)"},{transform:"scale(1)"}], {duration:300});
    }
  }

  function change(code, delta) {
    if (!cart[code]) return;
    cart[code].qty += delta;
    if (cart[code].qty <= 0) delete cart[code];
    save(); updateCount(); renderCart();
  }

  function updateCount() {
    document.querySelectorAll("#dukkani-cart-count, #dukkani-detail-cart-count, .dukkani-cart-count").forEach(el => { el.textContent = count(); });
  }
  function openCart() { renderCart(); document.getElementById("dukkani-cart-overlay").classList.add("open"); }
  function closeCart() { document.getElementById("dukkani-cart-overlay").classList.remove("open"); }

  document.addEventListener("click", event => {
    const trigger = event.target.closest("#dukkani-header-cart-button");
    if (!trigger) return;
    event.preventDefault();
    if (!document.getElementById("dukkani-cart-overlay")) installUI();
    openCart();
  });

  function renderCart() {
    const rows = Object.entries(cart);
    const items = document.getElementById("dukkani-cart-items");
    const footer = document.getElementById("dukkani-cart-footer");
    if (!rows.length) { items.innerHTML = '<div class="dukkani-empty">السلة فاضية حاليًا</div>'; footer.innerHTML = ""; return; }
    items.innerHTML = rows.map(([code,row]) => `<div class="dukkani-row"><div><b>${row.name}</b><div>${money(row.rate)} EGP</div></div><div class="dukkani-qty"><button data-code="${code}" data-delta="-1">−</button><b>${row.qty}</b><button data-code="${code}" data-delta="1">+</button></div></div>`).join("");
    footer.innerHTML = `<div class="dukkani-total"><span>الإجمالي</span><span>${money(total())} EGP</span></div><div class="dukkani-form"><label>بيانات التوصيل</label><input id="dukkani-name" placeholder="الاسم بالكامل"><input id="dukkani-email" type="email" placeholder="البريد الإلكتروني لتأكيد الطلب"><input id="dukkani-phone" placeholder="رقم الموبايل"><input id="dukkani-city" placeholder="المدينة"><input id="dukkani-district" placeholder="الحي / المنطقة"><input id="dukkani-address" placeholder="الشارع، رقم المبنى والشقة"><button type="button" class="dukkani-location">📍 تحديد موقعي الجغرافي</button><div class="dukkani-location-note"></div><label>طريقة الدفع</label><div class="dukkani-payment"><label><input type="radio" name="dukkani-payment" value="الدفع عند الاستلام" checked> 💵 الدفع عند الاستلام</label></div><button class="dukkani-checkout">إتمام الطلب</button><div class="dukkani-msg"></div></div>`;
    try {
      const draft = JSON.parse(localStorage.getItem(CHECKOUT_DRAFT_KEY) || "null");
      if (draft) {
        ["name", "email", "phone", "city", "district", "address"].forEach(key => {
          const input = document.getElementById(`dukkani-${key}`);
          if (input && draft[key]) input.value = draft[key];
        });
        locationData.lat = draft.lat || null;
        locationData.lng = draft.lng || null;
      }
    } catch (error) {
      localStorage.removeItem(CHECKOUT_DRAFT_KEY);
    }
    const customer = currentCustomer();
    if (customer) {
      document.getElementById("dukkani-name").value = customer.name || "";
      const emailInput = document.getElementById("dukkani-email");
      emailInput.value = customer.email;
      emailInput.readOnly = true;
      emailInput.title = "البريد المرتبط بحساب العميل";
    }
    items.querySelectorAll("button").forEach(button => button.onclick = () => change(button.dataset.code, Number(button.dataset.delta)));
    footer.querySelector(".dukkani-checkout").onclick = checkout;
    footer.querySelector(".dukkani-location").onclick = getLocation;
  }

  function getLocation() {
    const note = document.querySelector(".dukkani-location-note");
    if (!navigator.geolocation) { note.textContent = "المتصفح لا يدعم تحديد الموقع."; return; }
    note.textContent = "جاري تحديد الموقع…";
    navigator.geolocation.getCurrentPosition(async position => {
      locationData.lat = position.coords.latitude.toFixed(6);
      locationData.lng = position.coords.longitude.toFixed(6);
      note.textContent = "تم تحديد الموقع، جاري تحميل العنوان…";
      try {
        const response = await fetch(`${API}/shop/reverse-geocode?lat=${encodeURIComponent(locationData.lat)}&lng=${encodeURIComponent(locationData.lng)}`);
        const address = await response.json();
        if (!response.ok) throw new Error(address.detail || "تعذّر تحميل العنوان");
        document.getElementById("dukkani-city").value = address.city || "";
        document.getElementById("dukkani-district").value = address.district || "";
        document.getElementById("dukkani-address").value = address.address || "";
        note.innerHTML = `✅ تم ملء بيانات العنوان — <a href="https://maps.google.com/?q=${locationData.lat},${locationData.lng}" target="_blank">عرض الخريطة</a>`;
      } catch (error) {
        note.innerHTML = `✅ تم تحديد الإحداثيات — <a href="https://maps.google.com/?q=${locationData.lat},${locationData.lng}" target="_blank">عرض الخريطة</a><br>${error.message}`;
      }
    }, () => { note.textContent = "تعذّر تحديد الموقع؛ اسمحي للمتصفح بالوصول إلى موقعك."; }, {enableHighAccuracy:true,timeout:12000});
  }

  async function checkout() {
    const field = id => document.getElementById(id).value.trim();
    const payment = (document.querySelector('input[name="dukkani-payment"]:checked') || {}).value || "الدفع عند الاستلام";
    const msg = document.querySelector(".dukkani-msg");
    const draft = {name:field("dukkani-name"), email:field("dukkani-email"), phone:field("dukkani-phone"), city:field("dukkani-city"), address:field("dukkani-address"), district:field("dukkani-district"), payment, lat:locationData.lat, lng:locationData.lng};
    if (!draft.name || !draft.email || !draft.phone || !draft.city || !draft.address) { msg.textContent = "من فضلك كمّلي الاسم والبريد والموبايل والمدينة والعنوان."; return; }
    if (!customerIsLoggedIn()) {
      localStorage.setItem(CHECKOUT_DRAFT_KEY, JSON.stringify(draft));
      location.href = "/customer-login?next=checkout";
      return;
    }
    const customer = currentCustomer();
    const payload = {customer_name:draft.name, email:customer.email, phone:draft.phone, city:draft.city, address:draft.address, district:draft.district, payment, lat:locationData.lat, lng:locationData.lng, items:Object.entries(cart).map(([code,row]) => ({code, qty:row.qty, rate:row.rate}))};
    const button = document.querySelector(".dukkani-checkout"); button.disabled = true; button.textContent = "جاري تسجيل الطلب…";
    try {
      const response = await fetch(`${API}/shop/order?store=${encodeURIComponent(STORE)}`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "تعذّر تسجيل الطلب");
      Object.keys(cart).forEach(key => delete cart[key]); save(); updateCount(); localStorage.removeItem(CHECKOUT_DRAFT_KEY);
      document.getElementById("dukkani-cart-panel").innerHTML = `<div class="dukkani-empty"><h2>✅ تم تسجيل طلبك</h2><p>رقم الطلب: <b>${data.order}</b></p><p>الإجمالي: <b>${money(data.total)} ${data.currency || "EGP"}</b></p><button class="dukkani-checkout" onclick="location.reload()">الرجوع للمتجر</button></div>`;
    } catch (error) { msg.textContent = error.message; button.disabled = false; button.textContent = "إتمام الطلب"; }
  }

  function productCards() {
    return Array.from(document.querySelectorAll("#products article"));
  }

  function senseProductCategory(product) {
    const text = `${product?.name || ""} ${product?.code || ""} ${product?.desc || ""}`.toLowerCase();
    const code = String(product?.code || "").toUpperCase();
    if (code.includes("ELF") || /makeup|highlighter/.test(text)) return "makeup";
    if (code === "SENSE-009" || code === "SENSE-010" || /care|serum|crystal/.test(text)) return "care";
    if (/perfume|fragrance/.test(text)) return "perfume";
    if (/nail/.test(text)) return "nails";
    return "devices";
  }

  function filterSenseProducts(category = "all") {
    activeSenseCategory = category;
    productCards().forEach((card, index) => {
      const product = products[index];
      card.style.display = category === "all" || (product && senseProductCategory(product) === category) ? "" : "none";
    });
    const target = document.getElementById("products");
    if (target) target.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function bindSenseCategoryCards(root) {
    if (!root) return;
    root.querySelectorAll("a").forEach(card => {
      if (card.dataset.senseCategoryBound === "1") return;
      const text = card.textContent.toLowerCase();
      const category = /مكياج|makeup/.test(text) ? "makeup"
        : /عناية|care/.test(text) ? "care"
        : /أجهزة|اجهزة|device/.test(text) ? "devices"
        : /عطور|عطر|perfume|fragrance/.test(text) ? "perfume"
        : /أظافر|اظافر|nail/.test(text) ? "nails" : "all";
      card.dataset.senseCategoryBound = "1";
      card.dataset.category = category;
      card.href = "/#products";
      card.addEventListener("click", event => {
        event.preventDefault();
        filterSenseProducts(category);
      });
    });
    const imageCategory = image => {
      const source = String(image?.currentSrc || image?.src || "").toLowerCase();
      if (source.includes("category-makeup") || source.includes("promo-makeup")) return "makeup";
      if (source.includes("category-care") || source.includes("promo-care")) return "care";
      if (source.includes("category-devices") || source.includes("promo-devices")) return "devices";
      if (source.includes("category-perfume") || source.includes("promo-perfume")) return "perfume";
      if (source.includes("category-nails")) return "nails";
      return null;
    };
    root.querySelectorAll("img").forEach((image, index) => {
      if (image.dataset.senseCategoryBound === "1") return;
      const category = imageCategory(image) || ["makeup", "care", "devices", "perfume", "nails", "all"][index] || "all";
      image.dataset.senseCategoryBound = "1";
      let card = image.closest("a,button,[role='button']") || image.parentElement;
      if (card && card !== root) {
        card.style.cursor = "pointer";
        card.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation();
          filterSenseProducts(category);
        });
      }
    });
  }

  function installSenseCategoryDelegation() {
    if (STORE !== "sense" || document.documentElement.dataset.senseCategoryDelegation === "1") return;
    document.documentElement.dataset.senseCategoryDelegation = "1";
    document.addEventListener("click", event => {
      const image = event.target.closest("img");
      const source = String(image?.currentSrc || image?.src || "").toLowerCase();
      if (!image || !source.includes("sense-brand-")) return;
      const category = source.includes("makeup") ? "makeup"
        : source.includes("care") ? "care"
        : source.includes("devices") ? "devices"
        : source.includes("perfume") ? "perfume"
        : source.includes("nails") ? "nails" : null;
      if (!category) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      filterSenseProducts(category);
      history.replaceState(null, "", "#products");
    }, true);
  }

  function setProductButtonsLoading(loading) {
    productCards().forEach(card => {
      const button = card.querySelector('[data-product-code], .dukkani-add');
      if (!button) return;
      if (!button.dataset.readyText) button.dataset.readyText = button.textContent;
      button.disabled = loading;
      button.setAttribute("aria-busy", loading ? "true" : "false");
      button.style.opacity = "";
      button.textContent = button.dataset.readyText;
    });
  }

  function showProductError(onRetry) {
    let message = document.getElementById("dukkani-products-error");
    if (!message) {
      message = document.createElement("div");
      message.id = "dukkani-products-error";
      message.setAttribute("role", "alert");
      message.style.cssText = "margin:12px auto;padding:12px 16px;max-width:720px;text-align:center;border:1px solid #fecaca;border-radius:10px;background:#fef2f2;color:#991b1b;font:700 14px Tajawal,Arial";
      const section = document.getElementById("products");
      if (section) section.prepend(message);
    }
    message.innerHTML = 'تعذّر تجهيز السلة مؤقتًا. <button type="button" style="border:0;background:none;color:inherit;text-decoration:underline;cursor:pointer;font:inherit">حاولي مرة أخرى</button>';
    message.querySelector("button").onclick = onRetry;
  }

  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

  function normalizeImages(product) {
    const images = Array.isArray(product.images) ? product.images : [];
    const unique = [];
    images.concat(product.image ? [product.image] : []).forEach(src => {
      if (typeof src !== "string") return;
      const value = src.trim();
      if (value && !unique.includes(value)) unique.push(value);
    });
    return unique;
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function productDetailUrl(code) {
    const url = new URL(location.href);
    url.searchParams.set("product", code);
    url.hash = "";
    return url.pathname + url.search;
  }

  function findProduct(code) {
    const decoded = decodeURIComponent(code || "");
    return products.find(row => String(row.code) === decoded);
  }

  function productDescriptionHtml(product) {
    const text = product.desc || product.description || "لا يوجد وصف تفصيلي لهذا المنتج.";
    return escapeHtml(text).replace(/\n+/g, "<br>");
  }

  function relatedProducts(product) {
    const currentCode = String(product.code || "");
    return products.filter(row => String(row.code || "") !== currentCode).slice(0, 4);
  }

  function renderProductReviews(product) {
    const reviews = Array.isArray(product.reviews) ? product.reviews : [];
    if (!reviews.length) {
      return `<div class="dukkani-review">لا توجد تقييمات لهذا المنتج حتى الآن.</div>`;
    }
    return reviews.map(review => {
      const rating = Math.max(1, Math.min(5, Number(review.rating) || 1));
      return `<div class="dukkani-review">
        <div class="dukkani-review-stars">${"★".repeat(rating)}${"☆".repeat(5 - rating)}</div>
        <strong>${escapeHtml(review.name || "عميل")}</strong>
        <p>${escapeHtml(review.comment || "")}</p>
      </div>`;
    }).join("");
  }

  function renderProductDetail(product, replaceHistory) {
    if (!product) return;
    const existing = document.getElementById("dukkani-product-detail-page");
    if (existing) existing.remove();
    const images = normalizeImages(product);
    const mainImage = images[0] || product.image || "https://placehold.co/900x900/f3f4f6/64748b?text=Product";
    const outOfStock = Boolean(product.out_of_stock);
    const detail = document.createElement("main");
    detail.id = "dukkani-product-detail-page";
    detail.innerHTML = `
      <div class="dukkani-detail-wrap">
        <button type="button" class="dukkani-detail-back">← الرجوع للمتجر</button>
        <div class="dukkani-detail-grid">
          <div class="dukkani-detail-gallery">
            <div class="dukkani-detail-main-image"><img src="${escapeHtml(mainImage)}" alt="${escapeHtml(product.name || "")}"></div>
            <div class="dukkani-detail-thumbs">
              ${images.map((src, index) => `<button type="button" class="${index === 0 ? "active" : ""}" data-src="${escapeHtml(src)}"><img src="${escapeHtml(src)}" alt="${escapeHtml(product.name || "")}"></button>`).join("")}
            </div>
          </div>
          <div class="dukkani-detail-info">
            <h1>${escapeHtml(product.name || "")}</h1>
            <div class="dukkani-detail-code">${escapeHtml(product.code || "")}</div>
            <div class="dukkani-detail-price">${money(product.rate)} ${escapeHtml(storeCurrency)}</div>
            <div class="dukkani-detail-stock ${outOfStock ? "out" : "in"}">${outOfStock ? "غير متوفر" : "متوفر"}</div>
            <div class="dukkani-detail-desc">${product.desc || product.description || "لا يوجد وصف تفصيلي لهذا المنتج."}</div>
            <button type="button" class="dukkani-detail-add" ${outOfStock ? "disabled" : ""}>أضف للسلة</button>
            <section class="dukkani-detail-reviews">
              <h2>تقييمات المنتج</h2>
              ${renderProductReviews(product)}
            </section>
          </div>
        </div>
      </div>`;
    const footer = document.querySelector(".sense-footer");
    if (footer) document.body.insertBefore(detail, footer);
    else document.body.appendChild(detail);
    document.body.classList.add("dukkani-detail-open");
    const main = detail.querySelector(".dukkani-detail-main-image img");
    detail.querySelectorAll(".dukkani-detail-thumbs button").forEach(button => {
      button.addEventListener("click", () => {
        detail.querySelectorAll(".dukkani-detail-thumbs button").forEach(row => row.classList.remove("active"));
        button.classList.add("active");
        main.src = button.dataset.src || main.src;
      });
    });
    detail.querySelector(".dukkani-detail-add").addEventListener("click", () => add(product.code));
    detail.querySelector(".dukkani-detail-back").addEventListener("click", () => closeProductDetail(true));
    if (replaceHistory) history.pushState({ product: product.code }, "", productDetailUrl(product.code));
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  function renderSenseReviews(product) {
    const reviews = Array.isArray(product.reviews) ? product.reviews : [];
    if (!reviews.length) return `<div class="dukkani-review">لا توجد تقييمات لهذا المنتج حتى الآن.</div>`;
    return reviews.map(review => {
      const rating = Math.max(1, Math.min(5, Number(review.rating) || 1));
      return `<div class="dukkani-review">
        <div class="dukkani-review-stars">${"★".repeat(rating)}${"☆".repeat(5 - rating)}</div>
        <strong>${escapeHtml(review.name || "عميل")}</strong>
        <p>${escapeHtml(review.comment || "")}</p>
      </div>`;
    }).join("");
  }

  function renderSenseProductDetail(product, replaceHistory) {
    if (!product) return;
    const existing = document.getElementById("dukkani-product-detail-page");
    if (existing) existing.remove();
    const images = normalizeImages(product);
    const mainImage = images[0] || product.image || "https://placehold.co/900x900/f3f4f6/64748b?text=Product";
    const outOfStock = Boolean(product.out_of_stock);
    const related = relatedProducts(product);
    const footerElement = STORE === "sense"
      ? (document.querySelector(".sense-footer") || Array.from(document.querySelectorAll("footer")).find(footer => {
        const text = footer.textContent.replace(/\s+/g, " ").trim();
        return text.includes("CONTACT INFO") || text.includes("MY ACCOUNT") || text.includes("SUPPORT DESK");
      }))
      : null;
    const pageFooter = footerElement
      ? footerElement.outerHTML.replace('class="', 'class="sense-footer-detail ')
      : "";
    const detail = document.createElement("main");
    detail.id = "dukkani-product-detail-page";
    detail.innerHTML = `
      <div class="dukkani-detail-top">
        <div class="dukkani-detail-top-inner">
          <a class="dukkani-detail-logo" href="/">
            <span class="dukkani-detail-logo-mark">✥</span>
            <span>
              <span class="dukkani-detail-logo-text">SenSe</span>
              <span class="dukkani-detail-logo-sub">كوني الأجمل</span>
            </span>
          </a>
          <form class="dukkani-detail-search" action="/#products">
            <input type="search" placeholder="أنا أبحث عن..." aria-label="بحث">
            <button type="submit">⌕</button>
          </form>
          <div class="dukkani-detail-header-actions">
            <a href="/compare" aria-label="مقارنة">⇄ <b>0</b><span>مقارنة</span></a>
            <a href="/customer-account" aria-label="المفضلة">♡ <b>0</b><span>المفضلة</span></a>
            <button type="button" class="dukkani-detail-open-cart" aria-label="السلة">🛒 <b id="dukkani-detail-cart-count">${count()}</b><span>السلة</span></button>
          </div>
        </div>
        <nav class="dukkani-detail-nav" aria-label="روابط المتجر">
          <div class="dukkani-detail-nav-inner">
            <a href="/">الرئيسية</a>
            <a href="/#categories">الأقسام</a>
            <a href="/#products">المنتجات</a>
            <a href="/track-order">تتبع الطلب</a>
            <button type="button" class="dukkani-detail-back">العودة للمتجر</button>
          </div>
        </nav>
      </div>
      <div class="dukkani-detail-wrap">
        <div class="dukkani-detail-breadcrumb">
          <a href="/">الرئيسية</a> / <a href="/#products">المنتجات</a> / <strong>${escapeHtml(product.name || "")}</strong>
        </div>
        <div class="dukkani-detail-card">
          <div class="dukkani-detail-grid">
            <div class="dukkani-detail-gallery">
              <div class="dukkani-detail-main-image"><img src="${escapeHtml(mainImage)}" alt="${escapeHtml(product.name || "")}"></div>
              <div class="dukkani-detail-thumbs">
                ${(images.length ? images : [mainImage]).map((src, index) => `<button type="button" class="${index === 0 ? "active" : ""}" data-src="${escapeHtml(src)}"><img src="${escapeHtml(src)}" alt="${escapeHtml(product.name || "")}"></button>`).join("")}
              </div>
            </div>
            <div class="dukkani-detail-info">
              <h1>${escapeHtml(product.name || "")}</h1>
              <div class="dukkani-detail-rating">★★★★★ <span>لا توجد مراجعات بعد</span></div>
              <div class="dukkani-detail-meta">
                <div>الحالة: <b>${outOfStock ? "غير متوفر" : "متوفر"}</b></div>
                <div>كود المنتج: <b class="dukkani-detail-code">${escapeHtml(product.code || "")}</b></div>
              </div>
              <div class="dukkani-detail-price">${money(product.rate)} ${escapeHtml(storeCurrency)}</div>
              <div class="dukkani-detail-stock ${outOfStock ? "out" : "in"}">${outOfStock ? "غير متوفر" : "متوفر"}</div>
              <p class="dukkani-detail-short">${productDescriptionHtml(product)}</p>
              <div class="dukkani-detail-actions">
                <div class="dukkani-detail-qty" aria-label="الكمية">
                  <button type="button" class="dukkani-detail-minus">−</button>
                  <strong class="dukkani-detail-qty-value">1</strong>
                  <button type="button" class="dukkani-detail-plus">+</button>
                </div>
                <button type="button" class="dukkani-detail-add" ${outOfStock ? "disabled" : ""}>إضافة إلى السلة</button>
                <button type="button" class="dukkani-detail-buy" ${outOfStock ? "disabled" : ""}>اشتر الآن</button>
              </div>
              <div class="dukkani-detail-mini-actions">
                <button type="button" title="المفضلة">♡</button>
                <button type="button" title="مشاركة">↗</button>
                <a href="https://wa.me/?text=${encodeURIComponent((product.name || "") + " " + location.origin + productDetailUrl(product.code))}" target="_blank" rel="noopener" title="واتساب">☏</a>
              </div>
            </div>
          </div>
        </div>
        <section class="dukkani-detail-tabs">
          <h2>الوصف</h2>
          <div class="dukkani-detail-desc">${productDescriptionHtml(product)}</div>
          <div class="dukkani-detail-reviews">
            <h2>تقييمات المنتج</h2>
            ${renderSenseReviews(product)}
          </div>
        </section>
        ${related.length ? `<section class="dukkani-related">
          <h2>منتجات مشابهة</h2>
          <div class="dukkani-related-grid">
            ${related.map(row => {
              const image = normalizeImages(row)[0] || row.image || "https://placehold.co/600x600/f3f4f6/64748b?text=Product";
              return `<article class="dukkani-related-card" data-code="${escapeHtml(row.code || "")}">
                <img src="${escapeHtml(image)}" alt="${escapeHtml(row.name || "")}">
                <h3>${escapeHtml(row.name || "")}</h3>
                <strong>${money(row.rate)} ${escapeHtml(storeCurrency)}</strong>
              </article>`;
            }).join("")}
          </div>
        </section>` : ""}
      </div>
      ${pageFooter}`;
    document.body.appendChild(detail);
    document.body.classList.add("dukkani-detail-open");
    window.scrollTo(0, 0);
    requestAnimationFrame(() => window.scrollTo(0, 0));
    const main = detail.querySelector(".dukkani-detail-main-image img");
    detail.querySelectorAll(".dukkani-detail-thumbs button").forEach(button => {
      button.addEventListener("click", () => {
        detail.querySelectorAll(".dukkani-detail-thumbs button").forEach(row => row.classList.remove("active"));
        button.classList.add("active");
        main.src = button.dataset.src || main.src;
      });
    });
    let qty = 1;
    const qtyValue = detail.querySelector(".dukkani-detail-qty-value");
    const setQty = value => {
      qty = Math.max(1, Math.min(99, Number(value) || 1));
      qtyValue.textContent = qty;
    };
    detail.querySelector(".dukkani-detail-minus").addEventListener("click", () => setQty(qty - 1));
    detail.querySelector(".dukkani-detail-plus").addEventListener("click", () => setQty(qty + 1));
    const addQty = () => {
      for (let index = 0; index < qty; index += 1) add(product.code);
    };
    detail.querySelector(".dukkani-detail-add").addEventListener("click", addQty);
    detail.querySelector(".dukkani-detail-buy").addEventListener("click", () => {
      addQty();
      openCart();
    });
    detail.querySelectorAll(".dukkani-detail-back").forEach(button => button.addEventListener("click", () => closeProductDetail(true)));
    detail.querySelector(".dukkani-detail-open-cart").addEventListener("click", openCart);
    detail.querySelectorAll(".dukkani-related-card").forEach(card => card.addEventListener("click", () => openProductDetail(card.dataset.code)));
    if (replaceHistory) history.pushState({ product: product.code }, "", productDetailUrl(product.code));
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  function closeProductDetail(updateHistory) {
    const detail = document.getElementById("dukkani-product-detail-page");
    if (detail) detail.remove();
    document.body.classList.remove("dukkani-detail-open");
    if (updateHistory) {
      const url = new URL(location.href);
      url.searchParams.delete("product");
      history.pushState({}, "", url.pathname + url.search + url.hash);
    }
  }

  function openProductDetail(code, replaceHistory = true) {
    const product = findProduct(code);
    if (!product) return;
    renderSenseProductDetail(product, replaceHistory);
  }

  function openInitialProductDetail() {
    const code = new URLSearchParams(location.search).get("product");
    if (code) openProductDetail(code, false);
  }

  function syncProductRoute() {
    const code = new URLSearchParams(location.search).get("product");
    if (code) openProductDetail(code, false);
    else closeProductDetail(false);
  }

  window.addEventListener("popstate", syncProductRoute);
  window.addEventListener("hashchange", syncProductRoute);

  function installProductCarousel(card, product) {
    const images = normalizeImages(product);
    if (images.length < 2 || card.querySelector(".dukkani-product-carousel")) return;
    const firstImage = card.querySelector("img");
    if (!firstImage) return;
    const parent = firstImage.parentElement;
    const nextSibling = firstImage.nextSibling;
    const carousel = document.createElement("div");
    carousel.className = "dukkani-product-carousel";
    carousel.style.width = firstImage.style.width || "100%";
    carousel.style.height = firstImage.style.height || "";
    carousel.style.aspectRatio = firstImage.style.aspectRatio || getComputedStyle(firstImage).aspectRatio || "1 / 1";
    if (!carousel.style.aspectRatio || carousel.style.aspectRatio === "auto") carousel.style.aspectRatio = "1 / 1";
    images.forEach((src, imageIndex) => {
      const image = imageIndex === 0 ? firstImage : document.createElement("img");
      image.src = src;
      image.alt = firstImage.alt || product.name || "";
      image.classList.toggle("active", imageIndex === 0);
      carousel.appendChild(image);
    });
    const dots = document.createElement("div");
    dots.className = "dukkani-product-dots";
    images.forEach((_, dotIndex) => {
      const dot = document.createElement("span");
      dot.classList.toggle("active", dotIndex === 0);
      dots.appendChild(dot);
    });
    carousel.appendChild(dots);
    parent.insertBefore(carousel, nextSibling);
    let current = 0;
    const slides = Array.from(carousel.querySelectorAll("img"));
    const dotList = Array.from(dots.children);
    window.setInterval(() => {
      slides[current].classList.remove("active");
      dotList[current].classList.remove("active");
      current = (current + 1) % slides.length;
      slides[current].classList.add("active");
      dotList[current].classList.add("active");
    }, 3200);
  }

  async function loadExistingImage(src) {
    return new Promise(resolve => {
      const image = new Image();
      image.onload = () => resolve(src);
      image.onerror = () => resolve(null);
      image.src = src;
    });
  }

  async function installHeroCarousel() {
    const heroImage = Array.from(document.images).find(image =>
      /\/files\/[^/?]*brand-hero-\d+\.(jpe?g|png|webp)(\?|$)/i.test(image.currentSrc || image.src || "")
    );
    if (!heroImage || heroImage.dataset.dukkaniHeroCarousel === "1") return;
    const source = heroImage.currentSrc || heroImage.src || "";
    const match = source.match(/^(.*brand-hero-)\d+(\.(?:jpe?g|png|webp)(?:\?.*)?)$/i);
    if (!match) return;
    const candidates = [1, 2, 3, 4, 5].map(index => `${match[1]}${index}${match[2]}`);
    const slides = (await Promise.all(candidates.map(loadExistingImage))).filter(Boolean);
    if (slides.length < 2) return;
    let current = Math.max(0, slides.indexOf(source));
    heroImage.dataset.dukkaniHeroCarousel = "1";
    const parent = heroImage.parentElement;
    if (!parent) return;
    const nextSibling = heroImage.nextSibling;
    const computed = window.getComputedStyle(heroImage);
    const carousel = document.createElement("div");
    carousel.className = "dukkani-hero-carousel";
    carousel.style.width = heroImage.style.width || "100%";
    carousel.style.height = heroImage.style.height || computed.height || "";
    carousel.style.aspectRatio = heroImage.style.aspectRatio || computed.aspectRatio || "";
    if (!carousel.style.aspectRatio || carousel.style.aspectRatio === "auto") {
      carousel.style.aspectRatio = heroImage.naturalWidth && heroImage.naturalHeight
        ? `${heroImage.naturalWidth} / ${heroImage.naturalHeight}`
        : "16 / 9";
    }
    carousel.style.borderRadius = computed.borderRadius;
    const track = document.createElement("div");
    track.className = "dukkani-hero-track";
    slides.forEach((src, index) => {
      const slide = index === 0 ? heroImage : document.createElement("img");
      slide.src = src;
      slide.alt = heroImage.alt || "Dukkani hero";
      slide.removeAttribute("style");
      slide.dataset.dukkaniHeroCarousel = "1";
      track.appendChild(slide);
    });
    const dots = document.createElement("div");
    dots.className = "dukkani-hero-dots";
    const dotItems = slides.map((_, index) => {
      const dot = document.createElement("span");
      dot.className = index === current ? "active" : "";
      dots.appendChild(dot);
      return dot;
    });
    const render = () => {
      track.style.transform = `translateX(${current * 100}%)`;
      dotItems.forEach((dot, index) => dot.classList.toggle("active", index === current));
    };
    const next = () => {
      current = (current + 1) % slides.length;
      render();
    };
    carousel.appendChild(track);
    carousel.appendChild(dots);
    parent.insertBefore(carousel, nextSibling);
    render();
    window.setTimeout(next, 1000);
    window.setInterval(next, 3000);
  }

  function installSenseCategories() {
    if (STORE !== "sense") return;
    installSenseCategoryDelegation();
    if (document.getElementById("dukkani-sense-categories")) return;
    const existing = document.getElementById("categories");
    if (existing) {
      bindSenseCategoryCards(existing);
      document.querySelectorAll("img[src*='sense-brand-promo-']").forEach(image => bindSenseCategoryCards(image.closest("a") || image.parentElement));
      if (location.hash === "#categories") requestAnimationFrame(() => existing.scrollIntoView({ block: "start" }));
      return;
    }
    const section = document.createElement("section");
    section.id = "categories";
    section.className = "sense-categories";
    section.innerHTML = `
      <h2>الأقسام</h2>
      <p>تصفحي أقسام سينس الرئيسية واختاري منتجاتك بسهولة</p>
      <div id="dukkani-sense-categories" class="sense-category-grid">
        <a class="sense-category-card" data-category="makeup" href="/#products"><span class="sense-category-icon">💄</span><span>المكياج</span></a>
        <a class="sense-category-card" data-category="care" href="/#products"><span class="sense-category-icon">✨</span><span>العناية</span></a>
        <a class="sense-category-card" data-category="devices" href="/#products"><span class="sense-category-icon">💇</span><span>الأجهزة</span></a>
        <a class="sense-category-card" data-category="perfume" href="/#products"><span class="sense-category-icon">🌸</span><span>العطور</span></a>
        <a class="sense-category-card" data-category="nails" href="/#products"><span class="sense-category-icon">💅</span><span>الأظافر</span></a>
        <a class="sense-category-card" data-category="all" href="/#products"><span class="sense-category-icon">%</span><span>العروض والخصومات</span></a>
      </div>
    `;
    section.querySelectorAll("[data-category]").forEach(card => card.addEventListener("click", event => {
      event.preventDefault();
      filterSenseProducts(card.dataset.category);
    }));
    bindSenseCategoryCards(section);
    const productsSection = document.getElementById("products");
    const footer = document.querySelector(".sense-footer");
    const target = productsSection || footer;
    if (target && target.parentNode) target.parentNode.insertBefore(section, target);
    else document.body.appendChild(section);
    if (location.hash === "#categories") requestAnimationFrame(() => section.scrollIntoView({ block: "start" }));
  }

  function cleanSenseBuilderFooters() {
    if (STORE !== "sense") return;
    document.querySelectorAll("footer").forEach(footer => {
      const text = footer.textContent.replace(/\s+/g, " ").trim();
      const isPromoFooter = text.includes("سينس") && text.includes("الجمال والعناية") && !text.includes("CONTACT INFO");
      if (isPromoFooter) footer.remove();
    });
  }

  function installSenseFooter() {
    if (STORE !== "sense") return;
    cleanSenseBuilderFooters();
    const existingFullFooter = Array.from(document.querySelectorAll("footer")).find(footer => {
      const text = footer.textContent.replace(/\s+/g, " ").trim();
      return text.includes("CONTACT INFO") || text.includes("MY ACCOUNT") || text.includes("SUPPORT DESK");
    });
    if (document.querySelector(".sense-footer") || existingFullFooter) return;
    document.body.insertAdjacentHTML("beforeend", `
      <footer class="sense-footer">
        <div class="sense-footer-grid">
          <div class="sense-footer-brand">
            <img class="sense-footer-logo" src="/files/sense-brand-logo.png" alt="SenSe">
            <p>متجر إلكتروني خاص يبيع كل المنتجات التي تلبي احتياجاتك</p>
            <form class="sense-footer-newsletter" onsubmit="event.preventDefault()">
              <input type="email" placeholder="Your Email Address" aria-label="Your Email Address">
              <button type="submit">Subscribe</button>
            </form>
            <div class="sense-footer-seller"><a href="/signup">APPLY NOW</a><span>BE A SELLER</span></div>
          </div>
          <div class="sense-footer-col">
            <h3>مسجل لدي معروف</h3>
            <div class="sense-footer-app-icon">م</div>
          </div>
          <div class="sense-footer-col">
            <h3>CONTACT INFO</h3>
            <b>:Address</b><p>المملكة العربية السعودية - الرياض</p>
            <b>:Phone</b><p dir="ltr">0555601936</p>
            <b>:Email</b><p dir="ltr">info@sense.sa</p>
          </div>
          <div class="sense-footer-col">
            <h3>SUPPORT DESK</h3>
            <a href="/terms">Terms &amp; conditions</a>
            <a href="/return-policy">Return Policy</a>
            <a href="/privacy-policy">Privacy Policy</a>
          </div>
          <div class="sense-footer-col">
            <h3>MY ACCOUNT</h3>
            <a href="/customer-login">Login</a>
            <a href="/wishlist">My Wishlist</a>
            <a href="/track-order">Track Order</a>
          </div>
        </div>
        <div class="sense-footer-bottom">
          <div class="sense-footer-bottom-inner">
            <div class="sense-footer-payments">
              <span class="sense-footer-payment">MasterCard</span>
              <span class="sense-footer-payment">mada</span>
              <span class="sense-footer-payment">stc pay</span>
              <span class="sense-footer-payment"> Pay</span>
            </div>
            <div class="sense-footer-social">
              <a href="#" aria-label="Instagram">◎</a>
              <a href="#" aria-label="Twitter">t</a>
              <a href="#" aria-label="Facebook">f</a>
            </div>
            <div class="sense-footer-copy">جميع الحقوق محفوظة © 2026</div>
          </div>
        </div>
      </footer>
    `);
  }

  function installSenseWhatsApp() {
    if (STORE !== "sense" || document.querySelector(".sense-whatsapp")) return;
    document.body.insertAdjacentHTML("beforeend", `
      <a class="sense-whatsapp" href="https://wa.me/966555601936" target="_blank" rel="noopener" aria-label="WhatsApp">
        <svg viewBox="0 0 32 32" aria-hidden="true">
          <path d="M16.02 3.2A12.66 12.66 0 0 0 5.08 22.23L3.6 28.8l6.7-1.42A12.68 12.68 0 1 0 16.02 3.2Zm0 22.98c-1.95 0-3.84-.55-5.48-1.6l-.4-.25-3.95.84.87-3.85-.27-.42a10.29 10.29 0 1 1 9.23 5.28Zm5.63-7.72c-.31-.16-1.82-.9-2.1-1-.28-.1-.49-.16-.7.16-.2.31-.8 1-.98 1.2-.18.2-.36.23-.67.08-.31-.16-1.3-.48-2.48-1.52-.92-.82-1.54-1.83-1.72-2.14-.18-.31-.02-.48.14-.64.14-.14.31-.36.47-.54.16-.18.2-.31.31-.52.1-.2.05-.39-.03-.54-.08-.16-.7-1.68-.96-2.3-.25-.6-.5-.52-.7-.53h-.6c-.2 0-.54.08-.83.39-.28.31-1.08 1.05-1.08 2.56 0 1.5 1.1 2.96 1.26 3.16.16.2 2.17 3.31 5.25 4.64.73.32 1.31.51 1.75.65.74.23 1.41.2 1.94.12.59-.09 1.82-.74 2.08-1.46.26-.72.26-1.33.18-1.46-.08-.13-.28-.2-.59-.36Z"/>
        </svg>
      </a>
    `);
  }

  async function loadProducts() {
    let lastError;
    for (let attempt = 1; attempt <= PRODUCT_ATTEMPTS; attempt += 1) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), PRODUCT_TIMEOUT_MS);
      try {
        const response = await fetch(`${API}/shop/products?store=${encodeURIComponent(STORE)}`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error(`product request failed (${response.status})`);
        const data = await response.json();
        if (!Array.isArray(data.items) || !data.items.length) throw new Error("product list is empty");
        storeCurrency = data.currency || storeCurrency;
        return data.items;
      } catch (error) {
        lastError = error;
        if (attempt < PRODUCT_ATTEMPTS) await wait(attempt * 750);
      } finally {
        clearTimeout(timer);
      }
    }
    throw lastError || new Error("could not load products");
  }

  async function connectProductButtons() {
    const oldMessage = document.getElementById("dukkani-products-error");
    if (oldMessage) oldMessage.remove();
    setProductButtonsLoading(true);
    try {
      products = await loadProducts();
      filterSenseProducts(activeSenseCategory);
      productCards().forEach((card, index) => {
        const product = products[index]; if (!product) return;
        const button = card.querySelector('[data-product-code], .dukkani-add');
        if (!button) return;
        button.classList.add("dukkani-add");
        button.dataset.productCode = product.code;
        button.disabled = false;
        button.removeAttribute("aria-busy");
        button.style.opacity = "";
        button.textContent = button.dataset.readyText || button.textContent;
        button.onclick = event => {
          event.preventDefault();
          event.stopPropagation();
          add(product.code);
        };
        card.classList.add("dukkani-product-clickable");
        card.setAttribute("role", "link");
        card.setAttribute("tabindex", "0");
        card.addEventListener("click", event => {
          if (event.target.closest("button, a, input, textarea, select")) return;
          openProductDetail(product.code);
        });
        card.addEventListener("keydown", event => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          openProductDetail(product.code);
        });
        installProductCarousel(card, product);
      });
      syncThemeColors();
      openInitialProductDetail();
    } catch (error) {
      console.error("Dukkani cart:", error);
      setProductButtonsLoading(false);
      productCards().forEach(card => {
        const button = card.querySelector('[data-product-code], .dukkani-add');
        if (button) button.disabled = true;
      });
      showProductError(connectProductButtons);
    }
  }

  async function start() {
    syncThemeColors();
    installCustomerAccount();
    installSenseHeader();
    installUI();
    installHeroCarousel();
    installSenseCategories();
    installSenseFooter();
    installSenseWhatsApp();
    if (new URLSearchParams(location.search).get("resume") === "checkout" && count()) {
      document.getElementById("dukkani-cart-overlay").classList.add("open");
      renderCart();
    }
    await connectProductButtons();
    return;
    try {
      const response = await fetch(`${API}/shop/products?store=${encodeURIComponent(STORE)}`);
      const data = await response.json(); products = data.items || [];
      const cards = Array.from(document.querySelectorAll("#products article"));
      cards.forEach((card, index) => {
        const product = products[index]; if (!product) return;
        let button = card.querySelector('[data-product-code], .dukkani-add');
        if (!button) { button = document.createElement("button"); button.textContent = "أضف للسلة"; card.appendChild(button); }
        button.classList.add("dukkani-add"); button.dataset.productCode = product.code;
        button.onclick = () => add(product.code);
      });
      syncThemeColors();
    } catch (error) { console.error("Dukkani cart:", error); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
