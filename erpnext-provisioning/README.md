# تجهيز التاجر على ERPNext (Provisioning + Template)

هذا المجلد ينفّذ **الخطوتين 3 و 4** من فلو التجهيز:
> إنشاء Site معزول لكل تاجر ← ثم تطبيق قالب دكاني بداخله.

راجع الخطة الكاملة في [`../docs/ERPNext-Migration-Plan.md`](../docs/ERPNext-Migration-Plan.md).

## الملفات

| الملف | الدور |
|-------|-------|
| `tenant_template.py` | منطق القالب: يهيّئ موقع تاجر جديد (شركة + دليل حسابات + ضريبة + أدوار + وسائل دفع). آمن للتكرار. |
| `provision_tenant.sh` | المنسّق: ينشئ الـ Site ثم يطبّق القالب عليه، ويضبط الدومين. |

## ماذا يضبط القالب؟ (كله مستخرَج من كود دكاني — بلا اختراع)

| العنصر | القيمة | المصدر في دكاني |
|--------|--------|------------------|
| العملة | SAR | `orders.currency` الافتراضي |
| الدولة | Saudi Arabia | منصة سعودية |
| دليل الحسابات | Standard (يُنشأ تلقائياً مع الشركة) | ERPNext |
| ضريبة القيمة المضافة | 15% + قالب ضرائب مبيعات | ZATCA Phase 2 |
| الأدوار | Merchant Owner، Store Manager | `CLAUDE.md` (merchant_owner / store_manager) |
| وسائل الدفع | Moyasar، Tabby، Tamara | حزم دكاني للمدفوعات |
| مجموعة أصناف | Dukkani Products | — |

## التشغيل

```bash
# تاجر واحد
sudo bash provision_tenant.sh nourstore "Nour Fashion Store"

# النتيجة: http://nourstore.localhost:8080  (Administrator / admin)
```

كل تاجر يحصل على **قاعدة بيانات منفصلة تماماً** — هذا جوهر آلية العزل (Frappe Sites).

## ⚙️ إعداد ضروري: توجيه الدومين (Host-based routing)

في `frappe_docker/pwd.yml`، خدمة `frontend` تأتي افتراضياً بـ:
```yaml
FRAPPE_SITE_NAME_HEADER: frontend      # ← مثبّت على موقع واحد
```
هذا يجعل nginx يخدم موقع `frontend` **بغض النظر عن الدومين** — فكل التجار يظهر لهم نفس الموقع.
للـ multi-tenancy الحقيقي، غيّرها إلى:
```yaml
FRAPPE_SITE_NAME_HEADER: $$host        # ← يوجّه حسب الدومين
```
ثم أعد إنشاء الحاوية:
```bash
docker compose -f pwd.yml up -d --force-recreate frontend
```
بعدها كل `merchant.localhost:8080` يوجّه لموقع التاجر الصحيح. **(طُبّق واختُبر ✅)**

## ملاحظات مهمة

- **معالج الإعداد (Setup Wizard) في v16:** لا يكفي `System Settings.setup_complete`. الفلاغ الحقيقي الذي يفحصه `frappe.is_setup_complete()` هو حقل `is_setup_complete` على doctype **`Installed Application`** لكل تطبيق (frappe + erpnext). القالب يضبط الثلاثة (`UPDATE tabInstalled Application SET is_setup_complete=1` + `System Settings` + `desktop:home_page=workspace`) ثم يُمسح الكاش. لو ظهر المعالج رغم ذلك: `bench --site <SITE> clear-cache && clear-website-cache`.
- **ZATCA (تطبيق `ksa_compliance`):** غير مثبّت في صورة ERPNext الافتراضية. إضافته لاحقاً تتطلب `bench get-app` وإعادة بناء الصورة — مرحلة مستقلة. القالب الحالي يضبط ضريبة 15% محاسبياً فقط.
- **تقييد Store Manager من الشؤون المالية:** يُضبط لاحقاً عبر Role Permissions (القالب ينشئ الدور فقط).
- **الإنتاج:** غيّر `.localhost` إلى `.dukkani.ai` في `provision_tenant.sh`، واضبط Wildcard DNS (`*.dukkani.ai`) بدل `/etc/hosts`.
- **الأمان:** كلمات المرور هنا (`admin`) للتجربة فقط — يجب توليدها عشوائياً لكل تاجر في الإنتاج.

## Provisioning API + الأونبوردينج (مبني ✅)

مجلد `api/` يحوّل التجهيز إلى خدمة تناديها شاشة الأونبوردينج — الفلو الكامل من الأول للآخر.

| الملف | الدور |
|-------|-------|
| `api/main.py` | خدمة FastAPI: `POST /tenants` (إنشاء)، `GET /tenants/{sub}` (الحالة). |
| `api/provisioner.py` | يلفّ على `provision_tenant.sh` ويدير حالة كل تاجر في `tenants.json`. |
| `api/onboarding.html` | شاشة تسجيل التاجر (الخطوة 1) — تنادي الـ API وتتابع الحالة. |
| `api/run.sh` | يجهّز بيئة بايثون ويشغّل الخدمة على المنفذ 9000. |

### الفلو الكامل عند التشغيل

```
onboarding.html  →  POST /tenants  →  provision_tenant.sh  →  bench new-site + tenant_template.py
   (الخطوة 1)         (الخطوة 2)          (الخطوة 3+4)              (Site معزول + قالب)
```

### التشغيل

```bash
# 1) شغّل الخدمة (تحتاج صلاحية Docker → root)
cd api && sudo bash run.sh          # ترفع الـ API على http://localhost:9000

# 2) افتح شاشة الأونبوردينج في المتصفح
#    api/onboarding.html   (أو استخدم /docs للتجربة المباشرة)
```

### الاختبار عبر الطرفية (بدون واجهة)

```bash
curl -X POST http://localhost:9000/tenants \
  -H "Content-Type: application/json" \
  -d '{"subdomain":"nourstore","merchant_name":"Nour Fashion Store"}'

curl http://localhost:9000/tenants/nourstore     # متابعة الحالة
```

## الخطوة التالية

- تركيب تطبيق `ksa_compliance` (ZATCA) في الصورة كمرحلة مستقلة.
- ربط الأونبوردينج بتطبيق الموبايل (نفس الـ API).
- توليد كلمات مرور عشوائية لكل تاجر + إدارة أسرار.
