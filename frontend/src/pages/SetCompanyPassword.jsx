import { useState } from "react";
import { api, apiError, getTenantCnpj } from "../lib/api.js";

const basePath = import.meta.env.BASE_URL;

export default function SetCompanyPassword() {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [completed, setCompleted] = useState(false);
  const cnpj = getTenantCnpj();
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";

  const submit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    const confirmation = String(form.get("confirmation") || "");
    if (password !== confirmation) {
      setError("As senhas não correspondem.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      await api.post("/auth/setup-password", { token, password });
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      setCompleted(true);
    } catch (failure) {
      setError(apiError(failure.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="login-page">
      <a className="brand" href={basePath}>
        <span className="brand-mark">V</span>
        <span>Vitrine Virtual<small>Ativação de acesso</small></span>
      </a>
      <section className="login-card registration-card">
        {!completed ? (
          <>
            <p className="eyebrow">ACESSO DO ADMINISTRADOR</p>
            <h1>Crie sua senha</h1>
            <p>Use uma senha exclusiva com pelo menos 12 caracteres. O link de ativação só pode ser usado uma vez.</p>
            {!token || !cnpj ? (
              <p className="form-error">Este link está incompleto ou inválido. Solicite um novo convite ao responsável pela plataforma.</p>
            ) : (
              <form onSubmit={submit}>
                <label>Nova senha<input name="password" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></label>
                <label>Confirme a senha<input name="confirmation" type="password" required minLength={12} maxLength={128} autoComplete="new-password" /></label>
                {error && <p className="form-error">{error}</p>}
                <button className="button primary full" disabled={loading}>
                  {loading ? "Ativando acesso..." : "Definir senha e ativar acesso"}
                </button>
              </form>
            )}
          </>
        ) : (
          <>
            <p className="eyebrow">ACESSO ATIVADO</p>
            <h1>Senha definida</h1>
            <p>Seu acesso está pronto. Entre no painel da empresa com seu e-mail e a senha que acabou de criar.</p>
            <a className="button primary full" href={`${basePath}admin?cnpj=${encodeURIComponent(cnpj)}`}>
              Acessar painel da empresa
            </a>
          </>
        )}
      </section>
    </main>
  );
}
