import { useState } from "react";
import { api, apiError } from "../lib/api.js";

const basePath = import.meta.env.BASE_URL;

export default function CompanyRegistration() {
  const [company, setCompany] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    const cnpj = String(data.cnpj || "").replace(/\D/g, "");
    if (cnpj.length !== 14 || /^(\d)\1+$/.test(cnpj)) {
      setError("Informe um CNPJ válido com 14 dígitos.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const { data: created } = await api.post(
        "/platform/companies",
        {
          cnpj,
          store_name: data.store_name,
          email: data.email,
        },
        { headers: { "X-Setup-Secret": data.setup_secret } },
      );
      setCompany(created);
      form.reset();
    } catch (failure) {
      const status = failure.response?.status;
      if (status === 503) {
        setError("O cadastro ainda não está configurado no servidor. Confira o código mestre e tente novamente.");
      } else if (!failure.response) {
        setError("Não foi possível conectar à API. Aguarde o serviço iniciar e tente novamente.");
      } else {
        setError(apiError(failure.response.data?.detail));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="login-page">
      <a className="brand" href={basePath}>
        <span className="brand-mark">V</span>
        <span>Vitrine Virtual<small>Cadastro de empresas</small></span>
      </a>
      <form className="login-card registration-card" onSubmit={submit}>
        {!company ? (
          <>
            <p className="eyebrow">ACESSO DO PROPRIETÁRIO</p>
            <h1>Cadastrar empresa</h1>
            <p>Cadastre a empresa. O administrador receberá um convite por e-mail para criar a própria senha.</p>
            <label>Código mestre<input name="setup_secret" type="password" required autoComplete="off" /></label>
            <label>CNPJ<input name="cnpj" inputMode="numeric" placeholder="00.000.000/0000-00" required /></label>
            <label>Nome da empresa / loja<input name="store_name" required minLength={2} maxLength={160} /></label>
            <label>E-mail do administrador<input name="email" type="email" required autoComplete="off" /></label>
            {error && <p className="form-error">{error}</p>}
            <button className="button primary full" disabled={loading}>
              {loading ? "Cadastrando empresa..." : "Cadastrar empresa e administrador"}
            </button>
          </>
        ) : (
          <>
            <p className="eyebrow">CADASTRO CONCLUÍDO</p>
            <h1>{company.store_name}</h1>
            <p>A empresa foi cadastrada e o convite para definir a senha foi enviado ao administrador.</p>
            <div className="registration-summary">
              <p><strong>CNPJ:</strong> {company.cnpj}</p>
              <p><strong>Administrador:</strong> {company.email}</p>
              <p>O link de ativação expira em 24 horas e só pode ser usado uma vez.</p>
            </div>
            <a
              className="button primary full"
              href={`${basePath}admin?cnpj=${encodeURIComponent(company.cnpj)}`}
            >
              Abrir login desta empresa
            </a>
            <button className="button secondary full" type="button" onClick={() => setCompany(null)}>
              Cadastrar outra empresa
            </button>
          </>
        )}
      </form>
    </main>
  );
}
