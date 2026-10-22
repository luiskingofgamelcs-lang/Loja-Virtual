import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { api, getTenantCnpj, setTenantCnpj } from "../lib/api.js";

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth precisa ser usado dentro de AuthProvider.");
  return context;
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);

  useEffect(() => {
    let mounted = true;
    if (!getTenantCnpj()) {
      setUser(false);
      return () => {
        mounted = false;
      };
    }
    api
      .get("/auth/me")
      .then(({ data }) => {
        if (mounted) setUser(data);
      })
      .catch((error) => {
        if (error.response?.status !== 401) {
          console.error("Não foi possível verificar a sessão administrativa.", error);
        }
        if (mounted) setUser(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const login = async (cnpj, email, password) => {
    const selectedCnpj = setTenantCnpj(cnpj);
    const { data } = await api.post("/auth/login", { cnpj: selectedCnpj, email, password });
    setUser(data);
    return data;
  };

  const logout = async () => {
    await api.post("/auth/logout");
    setUser(false);
  };

  const value = useMemo(() => ({ user, setUser, login, logout }), [user]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
