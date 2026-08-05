(function () {
  // Store API routes are reverse-proxied on the current tenant host.
  const API = "";
  const STORE = location.hostname.split(".")[0];
  let products = [];
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
      .dukkani-hero-carousel{position:relative;display:block;overflow:hidden;border-radius:inherit}
      .dukkani-hero-track{display:flex;flex-direction:row-reverse;width:100%;height:100%;transition:transform .65s ease;will-change:transform}
      .dukkani-hero-track img{flex:0 0 100%;width:100%;height:100%;object-fit:cover;display:block}
      .dukkani-hero-dots{position:absolute;left:16px;right:16px;bottom:14px;display:flex;gap:7px;justify-content:center;pointer-events:none;z-index:2}
      .dukkani-hero-dots span{width:8px;height:8px;border-radius:999px;background:#fff8;border:1px solid #0002}
      .dukkani-hero-dots span.active{background:#fff}
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
    document.querySelectorAll("#dukkani-cart-count, .dukkani-cart-count").forEach(el => { el.textContent = count(); });
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
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
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
    carousel.appendChild(track);
    carousel.appendChild(dots);
    parent.insertBefore(carousel, nextSibling);
    render();
    window.setInterval(() => {
      current = (current + 1) % slides.length;
      render();
    }, 3800);
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
        button.onclick = () => add(product.code);
        installProductCarousel(card, product);
      });
      syncThemeColors();
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
    installUI();
    installHeroCarousel();
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
