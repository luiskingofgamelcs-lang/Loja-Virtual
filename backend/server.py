import asyncio
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
PLATFORM_ADMIN_EMAIL = os.getenv("PLATFORM_ADMIN_EMAIL", "").strip().lower()
PLATFORM_ADMIN_PASSWORD = os.getenv("PLATFORM_ADMIN_PASSWORD", "")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
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


def normalize_customer_document(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) not in {11, 14} or len(set(digits)) == 1:
        raise HTTPException(status_code=422, detail="Informe um CPF ou CNPJ válido")
    return digits


def tenant_database_name(cnpj: str) -> str:
    return f"store_{cnpj}"


def image_url(file_id: ObjectId) -> str:
    return f"/api/media/{file_id}?cnpj={tenant_cnpj.get()}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_temporary_password() -> str:
    return secrets.token_urlsafe(18)


def public_product(product: dict[str, Any], *, include_internal: bool = False) -> dict[str, Any]:
    result = dict(product)
    result["id"] = str(result.pop("_id", result.get("id", "")))
    if not include_internal:
        public_fields = {
            "id", "code", "name", "description", "category", "price",
            "stock", "unit", "variation", "image_url", "active",
        }
        result = {key: value for key, value in result.items() if key in public_fields}
    return result


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
    password: str = Field(min_length=1, max_length=128)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, password: str) -> str:
        if len(password.encode()) > 72:
            raise ValueError("A senha deve ter no máximo 72 bytes")
        return password


class CompanyRegistrationInput(BaseModel):
    cnpj: str
    store_name: str = Field(default="Vitrine Virtual", min_length=2, max_length=160)
    legal_name: str = Field(default="", max_length=200)
    email: EmailStr
    phone: str = Field(default="", max_length=30)
    business_address: str = Field(default="", max_length=300)


class PasswordChangeInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def new_password_fits_bcrypt(cls, password: str) -> str:
        if len(password.encode()) > 72:
            raise ValueError("A senha deve ter no máximo 72 bytes")
        return password


class PlatformLoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class CustomerAccountInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    person_type: str = Field(default="fisica")
    document: str = Field(default="", max_length=30)
    email: EmailStr
    phone: str = Field(default="", max_length=30)
    password: str = Field(min_length=8, max_length=128)
    address: str = Field(default="", max_length=240)
    neighborhood: str = Field(default="", max_length=120)
    city: str = Field(default="", max_length=120)
    postal_code: str = Field(default="", max_length=30)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, password: str) -> str:
        if len(password.encode()) > 72:
            raise ValueError("A senha deve ter no máximo 72 bytes")
        return password

    @field_validator("person_type")
    @classmethod
    def valid_person_type(cls, person_type: str) -> str:
        normalized = person_type.strip().lower()
        if normalized not in {"fisica", "juridica"}:
            raise ValueError("Tipo de pessoa inválido")
        return normalized


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
    logo_url: str = ""
    business_address: str = ""
    whatsapp_message: str = "Olá! Segue o resumo do seu pedido:"
    free_delivery_minimum: float = Field(default=0, ge=0)


def token_for(user_id: str, email: str, *, cnpj: str | None = None, scope: str = "tenant") -> str:
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "scope": scope,
        "exp": now_utc() + timedelta(hours=12),
    }
    if cnpj is not None:
        payload["cnpj"] = cnpj
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


async def current_user(request: Request) -> dict[str, Any]:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("scope") != "tenant":
            raise jwt.InvalidTokenError("Invalid scope")
        if payload.get("cnpj") != tenant_cnpj.get():
            raise jwt.InvalidTokenError("Token tenant mismatch")
        user = await db.users.find_one({"_id": payload["sub"], "role": {"$in": ["admin", "staff"]}})
    except (jwt.PyJWTError, KeyError, TypeError):
        user = None
    if not user:
        raise HTTPException(status_code=401, detail="Autenticação necessária")
    if user.get("password_change_required") and request.url.path not in {
        "/api/auth/change-password",
        "/api/auth/me",
    }:
        raise HTTPException(
            status_code=403,
            detail="Altere a senha temporária antes de continuar",
        )
    return user


async def current_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador")
    return user


async def current_platform_admin(request: Request) -> dict[str, Any]:
    token = request.cookies.get("platform_access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except (jwt.PyJWTError, TypeError, KeyError):
        raise HTTPException(status_code=401, detail="Autenticação de plataforma necessária")
    if payload.get("scope") != "platform":
        raise HTTPException(status_code=401, detail="Sessão de plataforma inválida")
    admin = await registry_db.platform_admins.find_one({"_id": payload["sub"]})
    if not admin:
        raise HTTPException(status_code=401, detail="Sessão de plataforma inválida")
    return admin


async def current_customer(request: Request) -> dict[str, Any]:
    customer = await optional_customer(request)
    if not customer:
        raise HTTPException(status_code=401, detail="Autenticação do cliente necessária")
    return customer


async def optional_customer(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get("customer_access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except (jwt.PyJWTError, TypeError, KeyError):
        raise HTTPException(status_code=401, detail="Sessão de cliente inválida")
    if payload.get("scope") != "customer" or payload.get("cnpj") != tenant_cnpj.get():
        raise HTTPException(status_code=401, detail="Sessão de cliente inválida")
    customer = await db.customer_accounts.find_one({"_id": payload["sub"]})
    if not customer:
        raise HTTPException(status_code=401, detail="Sessão de cliente inválida")
    return customer


@asynccontextmanager
async def lifespan(_: FastAPI):
    await registry_db.companies.create_index("cnpj", unique=True)
    await registry_db.companies.create_index("email", unique=True)
    await registry_db.platform_admins.create_index("email", unique=True)
    if PLATFORM_ADMIN_EMAIL and PLATFORM_ADMIN_PASSWORD:
        if len(PLATFORM_ADMIN_PASSWORD) < 12 or len(PLATFORM_ADMIN_PASSWORD.encode()) > 72:
            raise RuntimeError("PLATFORM_ADMIN_PASSWORD deve ter pelo menos 12 caracteres e no máximo 72 bytes")
        await registry_db.platform_admins.update_one(
            {"_id": "platform-admin"},
            {
                "$set": {
                    "email": PLATFORM_ADMIN_EMAIL,
                    "password_hash": bcrypt.hashpw(PLATFORM_ADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode(),
                    "name": "Administrador da plataforma",
                    "role": "platform",
                    "created_at": now_utc().isoformat(),
                }
            },
            upsert=True,
        )
    yield
    client.close()


app = FastAPI(title="Vitrine Virtual API", lifespan=lifespan)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.middleware("http")
async def select_tenant(request: Request, call_next):
    public_paths = {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/platform/auth",
        "/api/platform/companies",
        "/api/platform/logout",
    }
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path in public_paths or request.url.path.startswith("/api/platform/"):
        return await call_next(request)

    requested_cnpj = (
        request.headers.get("X-Store-CNPJ", "")
        or request.query_params.get("cnpj", "")
    ).strip()
    token = request.cookies.get("access_token") or request.cookies.get("customer_access_token", "")
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

    company = await registry_db.companies.find_one(
        {"cnpj": cnpj, "status": {"$ne": "suspended"}},
        {"_id": 0, "database": 1},
    )
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
    email = str(data.email).strip().lower()
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
                "status": "active",
                "owner_password_change_pending": True,
                "created_at": now_utc().isoformat(),
            }
        )
    except DuplicateKeyError as error:
        raise HTTPException(status_code=409, detail="CNPJ ou e-mail já cadastrado") from error

    database_name = tenant_database_name(cnpj)
    store_database = client[database_name]
    admin_id = str(uuid.uuid4())
    temporary_password = new_temporary_password()
    try:
        await store_database.users.insert_one(
            {
                "_id": admin_id,
                "email": email,
                "username": email,
                "name": data.store_name.strip(),
                "role": "admin",
                "password_hash": bcrypt.hashpw(
                    temporary_password.encode(),
                    bcrypt.gensalt(),
                ).decode(),
                "password_change_required": True,
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
                    business_address=data.business_address.strip(),
                ).model_dump()
            },
            upsert=True,
        )
    except Exception as error:
        try:
            await store_database.users.delete_one({"_id": admin_id})
            await registry_db.companies.delete_one({"cnpj": cnpj})
        except Exception:
            logger.exception("Failed to roll back company setup for CNPJ %s", cnpj)
        if isinstance(error, HTTPException):
            raise
        logger.exception("Failed to provision company for CNPJ %s", cnpj)
        raise HTTPException(status_code=500, detail="Não foi possível concluir o cadastro da empresa") from error

    return {
        "cnpj": cnpj,
        "store_name": data.store_name.strip(),
        "email": email,
        "temporary_password": temporary_password,
    }


@api_router.post("/platform/auth")
async def platform_login(data: PlatformLoginInput, response: Response):
    if not PLATFORM_ADMIN_EMAIL or not PLATFORM_ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Painel de plataforma não está configurado")
    email = data.email.strip().lower()
    admin = await registry_db.platform_admins.find_one({"email": email})
    if not admin:
        raise HTTPException(status_code=401, detail="Credenciais de plataforma inválidas")
    try:
        valid = (
            bcrypt.checkpw(data.password.encode(), admin["password_hash"].encode())
            if isinstance(admin.get("password_hash"), str)
            else False
        )
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(status_code=401, detail="Credenciais de plataforma inválidas")
    response.set_cookie(
        "platform_access_token",
        token_for(str(admin["_id"]), admin["email"], scope="platform"),
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="none" if os.getenv("COOKIE_SECURE", "false").lower() == "true" else "lax",
        max_age=43200,
        path="/",
    )
    return {"id": str(admin["_id"]), "email": admin["email"], "name": admin.get("name", "Plataforma")}


@api_router.post("/platform/logout")
async def platform_logout(response: Response):
    response.delete_cookie("platform_access_token", path="/")
    return {"ok": True}


@api_router.get("/platform/companies")
async def list_companies(_: dict[str, Any] = Depends(current_platform_admin)):
    companies = await registry_db.companies.find({}).sort("created_at", 1).to_list(1000)
    return [
        {
            "cnpj": company.get("cnpj", ""),
            "store_name": company.get("store_name", ""),
            "email": company.get("email", ""),
            "database": company.get("database", ""),
            "status": company.get("status", "active"),
            "owner_password_change_pending": company.get(
                "owner_password_change_pending",
                company.get("owner_setup_pending", False),
            ),
            "created_at": company.get("created_at", ""),
        }
        for company in companies
    ]


@api_router.patch("/platform/companies/{cnpj}/status")
async def set_company_status(
    cnpj: str,
    body: dict[str, str],
    _: dict[str, Any] = Depends(current_platform_admin),
):
    normalized = normalize_cnpj(cnpj)
    status = body.get("status")
    if status not in {"active", "suspended"}:
        raise HTTPException(status_code=422, detail="Status de empresa inválido")
    result = await registry_db.companies.update_one(
        {"cnpj": normalized},
        {"$set": {"status": status}},
    )
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return {"cnpj": normalized, "status": status}


@api_router.post("/customer/register")
async def register_customer(data: CustomerAccountInput):
    document = normalize_customer_document(data.document)
    email = data.email.strip().lower()
    accounts = db.customer_accounts
    await accounts.create_index("email", unique=True)
    await accounts.create_index("document", unique=True)
    await db.orders.create_index("customer_account_id")
    customer = {
        "_id": str(uuid.uuid4()),
        "name": data.name.strip(),
        "person_type": (data.person_type or "fisica").strip().lower(),
        "document": document,
        "email": email,
        "phone": data.phone.strip(),
        "password_hash": bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
        "address": data.address.strip(),
        "neighborhood": data.neighborhood.strip(),
        "city": data.city.strip(),
        "postal_code": data.postal_code.strip(),
        "created_at": now_utc().isoformat(),
        "updated_at": now_utc().isoformat(),
        "role": "customer",
    }
    try:
        await accounts.insert_one(customer)
    except DuplicateKeyError as error:
        raise HTTPException(
            status_code=409,
            detail="Já existe um cliente cadastrado com este e-mail ou documento",
        ) from error
    return {"id": customer["_id"], "name": customer["name"], "email": customer["email"], "person_type": customer["person_type"]}


@api_router.post("/customer/login")
async def customer_login(body: LoginInput, response: Response):
    if normalize_cnpj(body.cnpj) != tenant_cnpj.get():
        raise HTTPException(status_code=400, detail="O CNPJ informado não corresponde à empresa selecionada")
    email = body.email.strip().lower()
    customer = await db.customer_accounts.find_one({"email": email})
    if not customer:
        raise HTTPException(status_code=401, detail="Cliente ou senha inválidos")
    try:
        valid = (
            bcrypt.checkpw(body.password.encode(), customer["password_hash"].encode())
            if isinstance(customer.get("password_hash"), str)
            else False
        )
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(status_code=401, detail="Cliente ou senha inválidos")
    response.set_cookie(
        "customer_access_token",
        token_for(str(customer["_id"]), customer["email"], cnpj=tenant_cnpj.get(), scope="customer"),
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="none" if os.getenv("COOKIE_SECURE", "false").lower() == "true" else "lax",
        max_age=43200,
        path="/",
    )
    return {
        "id": str(customer["_id"]),
        "name": customer.get("name", "Cliente"),
        "email": customer.get("email", email),
        "phone": customer.get("phone", ""),
        "person_type": customer.get("person_type", "fisica"),
    }


@api_router.post("/customer/logout")
async def customer_logout(response: Response):
    response.delete_cookie("customer_access_token", path="/")
    return {"ok": True}


@api_router.get("/customer/me")
async def customer_me(current_customer_data: dict[str, Any] = Depends(current_customer)):
    return {
        "id": str(current_customer_data["_id"]),
        "name": current_customer_data.get("name", "Cliente"),
        "email": current_customer_data.get("email", ""),
        "phone": current_customer_data.get("phone", ""),
        "person_type": current_customer_data.get("person_type", "fisica"),
        "address": current_customer_data.get("address", ""),
        "neighborhood": current_customer_data.get("neighborhood", ""),
        "city": current_customer_data.get("city", ""),
        "postal_code": current_customer_data.get("postal_code", ""),
    }


@api_router.get("/customer/orders")
async def customer_orders(current_customer_data: dict[str, Any] = Depends(current_customer)):
    orders = await db.orders.find(
        {"customer_account_id": str(current_customer_data["_id"])}
    ).sort("created_at", -1).to_list(1000)
    return [
        {
            "id": str(order["_id"]),
            "status": order.get("status", "Pendente"),
            "payment_status": order.get("payment_status", "A receber"),
            "total": order.get("total", 0),
            "created_at": order.get("created_at", ""),
            "items": order.get("items", []),
        }
        for order in orders
    ]


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
    return [public_product(item, include_internal=True) for item in products]


@api_router.post("/admin/products")
async def create_product(data: ProductInput, _: dict[str, Any] = Depends(current_user)):
    product = data.model_dump()
    product["_id"] = str(uuid.uuid4())
    product["created_at"] = now_utc().isoformat()
    result = await db.products.insert_one(product)
    product["_id"] = result.inserted_id
    return public_product(product, include_internal=True)


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
        "logo_url": settings.get("logo_url", ""),
        "business_address": settings.get("business_address", ""),
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
async def create_order(
    data: OrderInput,
    customer_account: dict[str, Any] = Depends(current_customer),
):
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
            "status": "Pendente",
            "payment_method": "Na entrega",
            "payment_status": "A receber",
            "created_at": now_utc().isoformat(),
        }
        order["customer_account_id"] = str(customer_account["_id"])
        await db.orders.insert_one(order)
    except Exception:
        for product_id, quantity in updated:
            await db.products.update_one({"_id": product_id}, {"$inc": {"stock": quantity}})
        raise
    order["id"] = order.pop("_id")
    order.pop("customer_account_id", None)
    return order


@api_router.get("/admin/orders")
async def admin_orders(_: dict[str, Any] = Depends(current_user)):
    orders = await db.orders.find({}).sort("created_at", -1).to_list(1000)
    return [{"id": item.pop("_id"), **item} for item in orders]


@api_router.patch("/admin/orders/{order_id}")
async def update_order(order_id: str, body: dict[str, str], _: dict[str, Any] = Depends(current_user)):
    allowed_statuses = {"Pendente", "Pendente PIX", "Confirmado", "Em Separação", "Entregue"}
    updates: dict[str, str] = {}
    if "status" in body:
        status = body["status"]
        if status not in allowed_statuses:
            raise HTTPException(status_code=422, detail="Status inválido")
        updates["status"] = status
    if "payment_status" in body:
        payment_status = body["payment_status"]
        if payment_status not in {"A receber", "Pago na entrega"}:
            raise HTTPException(status_code=422, detail="Status de pagamento inválido")
        updates["payment_status"] = payment_status
    if not updates:
        raise HTTPException(status_code=422, detail="Informe o status do pedido ou do pagamento")
    result = await db.orders.update_one({"_id": order_id}, {"$set": updates})
    if not result.matched_count:
        raise HTTPException(status_code=404, detail="Pedido não encontrado")
    return {"id": order_id, **updates}


@api_router.get("/admin/customers")
async def admin_customers(_: dict[str, Any] = Depends(current_user)):
    customers = await db.customers.find({}, {"password_hash": 0}).sort("name", 1).to_list(1000)
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
    if order.get("payment_status") == "Pago na entrega":
        raise HTTPException(
            status_code=409,
            detail="Regularize o pagamento antes de cancelar este pedido",
        )
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
        token_for(str(user["_id"]), user.get("email") or user.get("username", ""), cnpj=tenant_cnpj.get(), scope="tenant"),
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="none" if os.getenv("COOKIE_SECURE", "false").lower() == "true" else "lax",
        max_age=43200,
        path="/",
    )
    return {
        "id": str(user["_id"]),
        "name": user.get("name", "Admin"),
        "email": user.get("email", ident),
        "username": user.get("username", ""),
        "role": user.get("role", "staff"),
        "must_change_password": user.get("password_change_required", False),
    }


@api_router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@api_router.post("/auth/change-password")
async def change_password(
    data: PasswordChangeInput,
    user: dict[str, Any] = Depends(current_user),
):
    try:
        valid = bcrypt.checkpw(
            data.current_password.encode(),
            user["password_hash"].encode(),
        )
    except (KeyError, ValueError):
        valid = False
    if not valid:
        raise HTTPException(status_code=400, detail="A senha atual está incorreta")

    password_hash = bcrypt.hashpw(data.new_password.encode(), bcrypt.gensalt()).decode()
    updated = await db.users.update_one(
        {"_id": user["_id"], "password_hash": user["password_hash"]},
        {
            "$set": {"password_hash": password_hash},
            "$unset": {"password_change_required": ""},
        },
    )
    if not updated.matched_count:
        raise HTTPException(status_code=409, detail="A senha foi alterada em outra sessão. Entre novamente.")

    user["password_hash"] = password_hash
    user.pop("password_change_required", None)
    if user.get("role") == "admin":
        await registry_db.companies.update_one(
            {"cnpj": tenant_cnpj.get()},
            {"$set": {"owner_password_change_pending": False}},
        )
    return {"ok": True}


@api_router.get("/auth/me")
async def auth_me(user: dict[str, Any] = Depends(current_user)):
    return {
        "id": str(user["_id"]),
        "name": user.get("name", "Admin"),
        "email": user.get("email", ""),
        "username": user.get("username", ""),
        "role": user.get("role", "staff"),
        "must_change_password": user.get("password_change_required", False),
    }


app.include_router(api_router)


@app.middleware("http")
async def protect_api_responses(request: Request, call_next):
    origin = request.headers.get("Origin")
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and origin
        and origin not in ALLOWED_ORIGINS
    ):
        return JSONResponse(status_code=403, content={"detail": "Origem não autorizada"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/media/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Store-CNPJ", "X-Setup-Secret"],
)
