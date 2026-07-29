# ============================================================
#  Dukkani — Provisioning API (FastAPI)
#  الخدمة التي تناديها شاشة الأونبوردينج (موبايل/ويب) لإنشاء تاجر.
#
#  التشغيل:  bash run.sh   (أو: uvicorn main:app --host 0.0.0.0 --port 9000)
#  التوثيق التفاعلي:  http://localhost:9000/docs
# ============================================================
import re

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

import provisioner as pv

app = FastAPI(
    title="Dukkani Provisioning API",
    description="تجهيز تاجر جديد على ERPNext: Site معزول + قالب دكاني.",
    version="0.1.0",
)

# الأونبوردينج قد يأتي من الموبايل أو الويب على أصول مختلفة
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TenantRequest(BaseModel):
    subdomain: str = Field(..., examples=["nourstore"])
    merchant_name: str = Field(..., min_length=2, max_length=80, examples=["Nour Fashion Store"])
    email: str | None = Field(None, examples=["owner@nour.com"])

    @field_validator("subdomain")
    @classmethod
    def _valid_subdomain(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.match(pv.SUBDOMAIN_RE, v):
            raise ValueError("النطاق الفرعي يجب أن يكون حروفاً/أرقاماً إنجليزية صغيرة و '-' (3–32 حرفاً).")
        if v in pv.RESERVED:
            raise ValueError(f"النطاق '{v}' محجوز، اختر اسماً آخر.")
        return v


@app.get("/health")
def health():
    return {"status": "ok", "service": "dukkani-provisioning"}


@app.get("/tenants")
def tenants():
    return pv.list_tenants()


@app.get("/tenants/{subdomain}")
def tenant_status(subdomain: str):
    record = pv.get_status(subdomain.lower())
    if not record:
        raise HTTPException(404, "التاجر غير موجود")
    return record


@app.post("/tenants", status_code=202)
def create_tenant(req: TenantRequest, background: BackgroundTasks):
    existing = pv.get_status(req.subdomain)
    if existing and existing.get("status") in {"provisioning", "ready"}:
        raise HTTPException(409, f"النطاق '{req.subdomain}' مستخدم بالفعل ({existing['status']}).")

    # الخطوة 2 في الفلو: استلام الطلب وبدء التجهيز في الخلفية
    pv.set_status(req.subdomain, status="pending", merchant_name=req.merchant_name,
                  email=req.email, url=f"http://{req.subdomain}.localhost:8080")
    background.add_task(pv.provision, req.subdomain, req.merchant_name)

    return {
        "subdomain": req.subdomain,
        "status": "pending",
        "message": "بدأ تجهيز متجرك — تابع الحالة عبر GET /tenants/{subdomain}",
        "status_url": f"/tenants/{req.subdomain}",
        "store_url": f"http://{req.subdomain}.localhost:8080",
    }
