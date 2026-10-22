import axios from "axios";

const backendUrl = import.meta.env.VITE_BACKEND_URL?.replace(/\/+$/, "");
const tenantKey = "store_cnpj";
const cnpjFromUrl = new URLSearchParams(window.location.search).get("cnpj");
let activeCnpj = (cnpjFromUrl || localStorage.getItem(tenantKey) || "").replace(/\D/g, "");

export const getTenantCnpj = () => {
  return activeCnpj;
};

export const setTenantCnpj = (cnpj) => {
  const normalized = String(cnpj || "").replace(/\D/g, "");
  if (!normalized) throw new Error("Informe o CNPJ da empresa.");
  activeCnpj = normalized;
  localStorage.setItem(tenantKey, normalized);
  api.defaults.headers.common["X-Store-CNPJ"] = normalized;
  return normalized;
};

export const api = axios.create({
  baseURL: backendUrl || "/api",
  withCredentials: true,
});

const initialCnpj = getTenantCnpj();
if (initialCnpj) api.defaults.headers.common["X-Store-CNPJ"] = initialCnpj;

api.interceptors.request.use((config) => {
  const cnpj = getTenantCnpj();
  if (cnpj) config.headers.set("X-Store-CNPJ", cnpj);
  return config;
});

export const brl = (value) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));

export const mediaUrl = (url) => {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  const absolutePath = url.startsWith("/") ? url : `/${url}`;
  return backendUrl ? `${backendUrl.replace(/\/api$/, "")}${absolutePath}` : absolutePath;
};

export const uploadImage = async (file) => {
  const body = new FormData();
  body.append("file", file);
  const { data } = await api.post("/admin/upload", body);
  return data;
};

export const apiError = (detail) => {
  if (detail == null) return "Não foi possível concluir a operação. Tente novamente.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg || JSON.stringify(item)).join(" ");
  return String(detail);
};
