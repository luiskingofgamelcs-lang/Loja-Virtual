import logging
import os
import re
import secrets
import uuid
from contextvars import ContextVar
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket
from pydantic import AliasChoices, BaseModel, EmailStr, Field, field_validator
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from gridfs.errors import NoFile
from starlette.responses import JSONResponse, Response

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "test_database")
PLATFORM_SETUP_SECRET = os.getenv("PLATFORM_SETUP_SECRET", "")
JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(32)
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
if not os.getenv("JWT_SECRET"):
    logger.warning("JWT_SECRET is unset; a temporary development secret is being used.")

client = AsyncIOMotorClient(MONGO_URL)
registry_db = client[DB_NAME]
tenant_db: ContextVar[Any | None] = ContextVar("tenant_db", default=None)
tenant_cnpj: ContextVar[str | None] = ContextVar("tenant_cnpj", default=None)


class TenantDatabase:
    def __getattr__(self, collection_name: str) -> Any:
        database = tenant_db.get()
        if database is None:
            raise RuntimeError("Tenant database accessed without tenant context")
        return getattr(database, collection_name)


db = TenantDatabase()
api_router = APIRouter(prefix="/api")


def normalize_cnpj(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 14 or len(set(digits)) == 1:
        raise HTTPException(status_code=422, detail="Informe um CNPJ válido com 14 dígitos")
    return digits


def tenant_database_name(cnpj: str) -> str:
    return f"store_{cnpj}"


def image_url(file_id: ObjectId) -> str:
    return f"/api/media/{file_id}?cnpj={tenant_cnpj.get()}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def public_product(product: dict[str, Any]) -> dict[str, Any]:
    product["id"] = str(product.pop("_id", product.get("id", "")))
    return product


def encode_pix(settings: dict[str, Any], amount: float, order_id: str) -> str:
    key = str(settings.get("pix_key", "")).strip()
    if not key:
        return ""

    def field(tag: str, value: str) -> str:
        return f"{tag}{len(value):02d}{value}"

    merchant = str(settings.get("pix_merchant_name", settings.get("store_name", "LOJA")))[:25]
    city = str(settings.get("pix_merchant_city", "SAO PAULO"))[:15]
    account = field("00", "br.gov.bcb.pix") + field("01", key)
    additional = field("05", order_id[:25])
    payload = (
        field("00", "01")
        + field("26", account)
        + field("52", "0000")
        + field("53", "986")
        + field("54", f"{amount:.2f}")
        + field("58", "BR")
        + field("59", merchant)
        + field("60", city)
        + field("62", additional)
        + "6304"
    )
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{payload}{crc:04X}"


class ProductInput(BaseModel):
    code: str = ""
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    category: str = "Geral"
    price: float = Field(gt=0)
    cost_price: float = Field(default=0, ge=0)
    stock: int = Field(ge=0)
    unit: str = "UN"
    variation: str = ""
    image_url: str = ""
    active: bool = True


class CustomerInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    phone: str = Field(default="", max_length=30)
    address: str = Field(default="", max_length=240)
    neighborhood: str = Field(
        default="",
        validation_alias=AliasChoices("neighborhood", "district"),
    )
    city: str = ""
    postal_code: str = Field(
        default="",
        validation_alias=AliasChoices("postal_code", "cep"),
    )
    notes: str = ""


class OrderLine(BaseModel):
    product_id: str
    quantity: int = Field(gt=0, le=500)
    variation: str = ""


class OrderInput(BaseModel):
    customer: CustomerInput
    items: list[OrderLine] = Field(min_length=1)


class LoginInput(BaseModel):
    cnpj: str
    email: str
    password: str


class CompanyRegistrationInput(BaseModel):
    cnpj: str
    store_name: str = Field(default="Vitrine Virtual", min_length=2, max_length=160)
    legal_name: str = Field(default="", max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone: str = Field(default="", max_length=30)
    pix_key: str = Field(default="", max_length=120)
    business_address: str = Field(default="", max_length=300)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, password: str) -> str:
        if len(password.encode()) > 72:
            raise ValueError("A senha deve ter no máximo 72 bytes")
        return password


class UserInput(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=160)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, password: str) -> str:
        if len(password.encode()) > 72:
            raise ValueError("A senha deve ter no máximo 72 bytes")
        return password


class SettingsInput(BaseModel):
    store_name: str = "Vitrine Virtual"
    legal_name: str = ""
    document: str = ""
    phone: str = ""
    pix_key: str = ""
    pix_merchant_name: str = "VITRINE VIRTUAL"
    pix_merchant_city: str = "SAO PAULO"
    logo_url: str = ""
    business_address: str = ""
    whatsapp_message: str = "Olá! Segue o resumo do seu pedido:"
    free_delivery_minimum: float = Field(default=0, ge=0)


def token_for(user_id: str, email: str) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "cnpj": tenant_cnpj.get(),
            "exp": now_utc() + timedelta(days=7),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


async def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("cnpj") != tenant_cnpj.get():
            raise jwt.InvalidTokenError("Token tenant mismatch")
        user = await db.users.find_one({"_id": payload["sub"], "role": {"$in": ["admin", "staff"]}})
    except (jwt.PyJWTError, KeyError, TypeError):
        user = None
    if not user:
        raise HTTPException(status_code=401, detail="Autenticação necessária")
    return user


async def current_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador")
    return user


@asynccontextmanager
async def lifespan(_: FastAPI):
    await registry_db.companies.create_index("cnpj", unique=True)
    await registry_db.companies.create_index("email", unique=True)
    yield
    client.close()


app = FastAPI(title="Vitrine Virtual API", lifespan=lifespan)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.middleware("http")
async def select_tenant(request: Request, call_next):
    public_paths = {"/health", "/api/platform/companies"}
    if request.method == "OPTIONS" or request.url.path in public_paths:
        return await call_next(request)

    requested_cnpj = (
        request.headers.get("X-Store-CNPJ", "")
        or request.query_params.get("cnpj", "")
    ).strip()
    token = request.cookies.get("access_token", "")
    if token and not requested_cnpj:
        try:
            requested_cnpj = jwt.decode(token, JWT_SECRET, algorithms=["HS256"]).get("cnpj", "")
        except jwt.PyJWTError:
            pass
    if not requested_cnpj:
        return JSONResponse(
            status_code=400,
            content={"detail": "Informe o CNPJ da empresa para acessar a loja"},
        )
    try:
        cnpj = normalize_cnpj(requested_cnpj)
    except HTTPException as error:
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})

    company = await registry_db.companies.find_one({"cnpj": cnpj}, {"_id": 0, "database": 1})
    if not company:
        return JSONResponse(status_code=404, content={"detail": "Empresa não cadastrada"})

    db_token = tenant_db.set(client[company["database"]])
    cnpj_token = tenant_cnpj.set(cnpj)
    try:
        return await call_next(request)
    finally:
        tenant_db.reset(db_token)
        tenant_cnpj.reset(cnpj_token)


@api_router.get("/")
async def root() -> dict[str, str]:
    return {"message": "Vitrine Virtual API"}


@api_router.post("/platform/companies", status_code=201)
async def register_company(data: CompanyRegistrationInput, request: Request):
    if not PLATFORM_SETUP_SECRET:
        raise HTTPException(status_code=503, detail="Cadastro de empresas não está configurado no servidor")
    setup_secret = request.headers.get("X-Setup-Secret", "")
    if not secrets.compare_digest(setup_secret, PLATFORM_SETUP_SECRET):
        raise HTTPException(status_code=403, detail="Acesso ao cadastro não autorizado")

    cnpj = normalize_cnpj(data.cnpj)
    email = data.email.strip().lower()
    existing = await registry_db.companies.find_one(
        {"$or": [{"cnpj": cnpj}, {"email": email}]}
    )
    if existing:
        raise HTTPException(status_code=409, detail="CNPJ ou e-mail já cadastrado")

    try:
        await registry_db.companies.insert_one(
            {
                "_id": cnpj,
                "cnpj": cnpj,
                "email": email,
                "store_name": data.store_name.strip(),
                "database": tenant_database_name(cnpj),
                "created_at": now_utc().isoformat(),
            }
        )
    except DuplicateKeyError as error:
        raise HTTPException(status_code=409, detail="CNPJ ou e-mail já cadastrado") from error

    database_name = tenant_database_name(cnpj)
    store_database = client[database_name]
    admin_id = str(uuid.uuid4())
    try:
        await store_database.users.insert_one(
            {
                "_id": admin_id,
                "email": email,
                "username": email,
                "name": data.store_name.strip(),
                "role": "admin",
                "password_hash": bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
                "created_at": now_utc().isoformat(),
            }
        )
        await store_database.settings.update_one(
            {"_id": "company"},
            {
                "$set": SettingsInput(
                    store_name=data.store_name.strip(),
                    legal_name=data.legal_name.strip(),
                    document=cnpj,
                    phone=data.phone.strip(),
                    pix_key=data.pix_key.strip(),
                    business_address=data.business_address.strip(),
                ).model_dump()
            },
            upsert=True,
        )
    except Exception:
        await store_database.users.delete_one({"_id": admin_id})
        await registry_db.companies.delete_one({"cnpj": cnpj})
        logger.exception("Failed to provision company for CNPJ %s", cnpj)
        raise HTTPException(status_code=500, detail="Não foi possível concluir o cadastro da empresa")

    return {
        "cnpj": cnpj,
        "store_name": data.store_name.strip(),
        "email": email,
    }


@api_router.get("/products")
async def list_products():
    products = await db.products.find(
        {"active": True, "stock": {"$gt": 0}}
    ).sort("name", 1).to_list(1000)
    return [public_product(item) for item in products]


@api_router.post("/admin/upload")
async def upload_image(file: UploadFile = File(...), _: dict[str, Any] = Depends(current_user)):
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Envie uma imagem JPEG, PNG, WebP ou GIF")
    contents = await file.read(MAX_IMAGE_SIZE + 1)
    if not contents:
        raise HTTPException(status_code=400, detail="O arquivo enviado está vazio")
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="A imagem deve ter no máximo 5 MB")

    database = tenant_db.get()
    if database is None:
        raise RuntimeError("Tenant database is not selected for image upload")
    gridfs = AsyncIOMotorGridFSBucket(database)
    filename = Path(file.filename or "imagem").name[:200]
    file_id = await gridfs.upload_from_stream(
        filename,
        contents,
        metadata={"content_type": content_type},
    )
    return {"id": str(file_id), "url": image_url(file_id)}


@api_router.get("/media/{file_id}")
async def get_image(file_id: str):
    if not ObjectId.is_valid(file_id):
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
    database = tenant_db.get()
    if database is None:
        raise RuntimeError("Tenant database is not selected for image download")
    gridfs = AsyncIOMotorGridFSBucket(database)
    try:
        stream = await gridfs.open_download_stream(ObjectId(file_id))
    except NoFile as error:
        raise HTTPException(status_code=404, detail="Imagem não encontrada") from error
    content = await stream.read()
    content_type = (stream.metadata or {}).get("content_type", "application/octet-stream")
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@api_router.get("/admin/products")
async def admin_products(_: dict[str, Any] = Depends(current_user)):
    products = await db.products.find({}).sort("name", 1).to_list(1000)
    return [public_product(item) for item in products]


@api_router.post("/admin/products")
async def create_product(data: ProductInput, _: dict[str, Any] = Depends(current_user)):
    product = data.model_dump()
    product["_id"] = str(uuid.uuid4())
    product["created_at"] = now_utc().isoformat()
    result = await db.products.insert_one(product)
    product["_id"] = result.inserted_id
    return public_product(product)


@api_router.put("/admin/products/{product_id}")
async def update_product(product_id: str, data: ProductInput, _: dict[str, Any] = Depends(current_user)):
    result = await db.products.update_one({"_id": product_id}, {"$set": data.model_dump()})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return {"id": product_id, **data.model_dump()}


@api_router.delete("/admin/products/{product_id}")
async def delete_product(product_id: str, _: dict[str, Any] = Depends(current_user)):
    result = await db.products.delete_one({"_id": product_id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return {"ok": True}


@api_router.get("/settings")
async def get_public_settings():
    settings = await db.settings.find_one({"_id": "company"}) or {}
    return {
        "store_name": settings.get("store_name", "Vitrine Virtual"),
        "phone": settings.get("phone", ""),
        "pix_key": settings.get("pix_key", ""),
        "pix_merchant_name": settings.get("pix_merchant_name", "VITRINE VIRTUAL"),
        "pix_merchant_city": settings.get("pix_merchant_city", "SAO PAULO"),
        "logo_url": settings.get("logo_url", ""),
        "business_address": settings.get("business_address", ""),
        "document": settings.get("document", ""),
        "whatsapp_message": settings.get("whatsapp_message", "Olá! Segue o resumo do seu pedido:"),
        "free_delivery_minimum": settings.get("free_delivery_minimum", 0),
    }


@api_router.get("/admin/settings")
async def get_admin_settings(_: dict[str, Any] = Depends(current_user)):
    settings = await db.settings.find_one({"_id": "company"})
    return SettingsInput(**{key: value for key, value in (settings or {}).items() if key != "_id"})


@api_router.put("/admin/settings")
async def save_settings(data: SettingsInput, _: dict[str, Any] = Depends(current_user)):
    await db.settings.update_one({"_id": "company"}, {"$set": data.model_dump()}, upsert=True)
    return data


@api_router.post("/orders")
async def create_order(data: OrderInput):
    settings = await db.settings.find_one({"_id": "company"}) or {}
    lines: list[dict[str, Any]] = []
    for line in data.items:
        product = await db.products.find_one(
            {"_id": line.product_id, "active": True, "stock": {"$gte": line.quantity}}
        )
        if not product:
            raise HTTPException(status_code=409, detail="Produto indisponível ou estoque insuficiente")
        lines.append(
            {
                "product_id": line.product_id,
                "name": product["name"],
                "unit_price": float(product["price"]),
                "quantity": line.quantity,
                "variation": line.variation or product.get("variation", ""),
                "subtotal": round(float(product["price"]) * line.quantity, 2),
            }
        )

    order_id = str(uuid.uuid4())
    updated: list[tuple[str, int]] = []
    try:
        for line in lines:
            result = await db.products.update_one(
                {"_id": line["product_id"], "active": True, "stock": {"$gte": line["quantity"]}},
                {"$inc": {"stock": -line["quantity"]}},
            )
            if not result.modified_count:
                raise HTTPException(status_code=409, detail="Estoque alterado. Atualize a vitrine e tente novamente.")
            updated.append((line["product_id"], line["quantity"]))

        customer = data.customer.model_dump()
        customer["updated_at"] = now_utc().isoformat()
        await db.customers.update_one(
            {"phone": customer["phone"]},
            {"$set": customer, "$setOnInsert": {"created_at": now_utc().isoformat()}},
            upsert=True,
        )
        total = round(sum(line["subtotal"] for line in lines), 2)
        order = {
            "_id": order_id,
            "customer": customer,
            "items": lines,
            "total": total,
            "status": "Pendente PIX",
            "created_at": now_utc().isoformat(),
            "pix_payload": encode_pix(settings, total, order_id),
        }
        await db.orders.insert_one(order)
    except Exception:
        for product_id, quantity in updated:
            await db.products.update_one({"_id": product_id}, {"$inc": {"stock": quantity}})
        raise
    order["id"] = order.pop("_id")
    return order


@api_router.get("/admin/orders")
async def admin_orders(_: dict[str, Any] = Depends(current_user)):
    orders = await db.orders.find({}).sort("created_at", -1).to_list(1000)
    return [{"id": item.pop("_id"), **item} for item in orders]


@api_router.patch("/admin/orders/{order_id}")
async def update_order(order_id: str, body: dict[str, str], _: dict[str, Any] = Depends(current_user)):
    allowed = {"Pendente PIX", "Confirmado", "Em Separação", "Entregue"}
    status = body.get("status")
    if status not in allowed:
        raise HTTPException(status_code=422, detail="Status inválido")
    result = await db.orders.update_one({"_id": order_id}, {"$set": {"status": status}})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return {"id": order_id, "status": status}


@api_router.get("/admin/customers")
async def admin_customers(_: dict[str, Any] = Depends(current_user)):
    customers = await db.customers.find({}).sort("name", 1).to_list(1000)
    for customer in customers:
        customer["id"] = str(customer.pop("_id", ""))
        customer["order_count"] = await db.orders.count_documents({"customer.phone": customer.get("phone")})
        customer["orders_count"] = customer["order_count"]
    return customers


@api_router.post("/admin/customers")
async def create_customer(data: CustomerInput, _: dict[str, Any] = Depends(current_user)):
    customer = data.model_dump()
    customer["_id"] = str(uuid.uuid4())
    customer["created_at"] = now_utc().isoformat()
    customer["updated_at"] = customer["created_at"]
    if customer["phone"] and await db.customers.find_one({"phone": customer["phone"]}):
        raise HTTPException(status_code=409, detail="Já existe um cliente com este telefone")
    await db.customers.insert_one(customer)
    customer["id"] = customer.pop("_id")
    customer["order_count"] = 0
    customer["orders_count"] = 0
    return customer


@api_router.delete("/admin/customers/{customer_id}")
async def delete_customer(customer_id: str, _: dict[str, Any] = Depends(current_user)):
    result = await db.customers.delete_one({"_id": customer_id})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return {"ok": True}


@api_router.delete("/admin/orders/{order_id}")
async def cancel_order(order_id: str, _: dict[str, Any] = Depends(current_user)):
    order = await db.orders.find_one({"_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    if order.get("status") == "Cancelado":
        raise HTTPException(status_code=409, detail="Este pedido já foi cancelado")
    result = await db.orders.update_one(
        {"_id": order_id, "status": {"$ne": "Cancelado"}},
        {"$set": {"status": "Cancelado", "cancelled_at": now_utc().isoformat()}},
    )
    if not result.modified_count:
        raise HTTPException(status_code=409, detail="O pedido já foi cancelado")
    try:
        for item in order.get("items", []):
            await db.products.update_one(
                {"_id": item["product_id"]},
                {"$inc": {"stock": item["quantity"]}},
            )
    except Exception:
        logger.exception("Failed to restore stock for cancelled order %s", order_id)
        raise HTTPException(
            status_code=500,
            detail="Pedido cancelado, mas não foi possível restaurar todo o estoque. Verifique o estoque manualmente.",
        )
    return {"id": order_id, "status": "Cancelado"}


@api_router.get("/admin/users")
async def list_users(_: dict[str, Any] = Depends(current_admin)):
    users = await db.users.find({}, {"password_hash": 0}).sort("created_at", 1).to_list(1000)
    return [
        {
            "id": str(user.get("_id", "")),
            "username": user.get("username", user.get("email", "")),
            "email": user.get("email", ""),
            "name": user.get("name", ""),
            "role": user.get("role", "staff"),
        }
        for user in users
    ]


@api_router.post("/admin/users")
async def create_user(data: UserInput, _: dict[str, Any] = Depends(current_admin)):
    username = data.username.strip().lower()
    if not username:
        raise HTTPException(status_code=422, detail="Informe um nome de usuário")
    if await db.users.find_one({"$or": [{"username": username}, {"email": username}]}):
        raise HTTPException(status_code=409, detail="Este usuário já existe")
    user = {
        "_id": str(uuid.uuid4()),
        "username": username,
        "email": username,
        "name": data.name.strip() or data.username.strip(),
        "password_hash": bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
        "role": "staff",
        "created_at": now_utc().isoformat(),
    }
    await db.users.insert_one(user)
    return {
        "id": user["_id"],
        "username": user["username"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
    }


@api_router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, admin: dict[str, Any] = Depends(current_admin)):
    if user_id == str(admin["_id"]):
        raise HTTPException(status_code=400, detail="Você não pode remover sua própria conta")
    result = await db.users.delete_one({"_id": user_id, "role": "staff"})
    if not result.deleted_count:
        raise HTTPException(status_code=404, detail="Usuário operador não encontrado")
    return {"ok": True}


@api_router.post("/auth/login")
async def login(body: LoginInput, response: Response):
    if normalize_cnpj(body.cnpj) != tenant_cnpj.get():
        raise HTTPException(status_code=400, detail="O CNPJ informado não corresponde à empresa selecionada")
    ident = body.email.strip().lower()
    user = await db.users.find_one({"$or": [{"email": ident}, {"username": ident}]})
    password_hash = user.get("password_hash") if user else None
    valid = False
    if isinstance(password_hash, str):
        try:
            valid = bcrypt.checkpw(body.password.encode(), password_hash.encode())
        except ValueError:
            valid = False
    if not valid or not user or user.get("role") not in {"admin", "staff"}:
        raise HTTPException(status_code=401, detail="Usuário/e-mail ou senha inválidos")
    response.set_cookie(
        "access_token",
        token_for(str(user["_id"]), user.get("email") or user.get("username", "")),
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="none" if os.getenv("COOKIE_SECURE", "false").lower() == "true" else "lax",
        max_age=604800,
        path="/",
    )
    return {
        "id": str(user["_id"]),
        "name": user.get("name", "Admin"),
        "email": user.get("email", ident),
        "username": user.get("username", ""),
        "role": user.get("role", "staff"),
    }


@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@api_router.get("/auth/me")
async def auth_me(user: dict[str, Any] = Depends(current_user)):
    return {
        "id": str(user["_id"]),
        "name": user.get("name", "Admin"),
        "email": user.get("email", ""),
        "username": user.get("username", ""),
        "role": user.get("role", "staff"),
    }


app.include_router(api_router)
origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Store-CNPJ", "X-Setup-Secret"],
)
