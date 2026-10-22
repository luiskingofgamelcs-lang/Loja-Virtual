import { useState } from "react";
import { api } from "../lib/api.js";

const basePath = import.meta.env.BASE_URL;

export default function CompanyRegistration() {
  const [company, setCompany] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    setLoading(true);
    setError("");
    try {
      const { data: created } = await api.post(
        "/platform/companies",
        {
          cnpj: data.cnpj,
          store_name: data.store_name,
          legal_name: data.legal_name,
          email: data.email,
          password: data.password,
          phone: data.phone,
          business_address: data.business_address,
        },
        { headers: { "X-Setup-Secret": data.setup_secret } },
      );
      setCompany(created);
      form.reset();
    } catch (failure) {
      setError(failure.response?.data?.detail || "Não foi possível cadastrar a empresa. Tente novamente.");
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
            <p>Cadastre a empresa e crie a conta do administrador. O CNPJ identificará o banco de dados da loja.</p>
            <label>Código mestre<input name="setup_secret" type="password" required autoComplete="off" /></label>
            <label>Nome da loja<input name="store_name" required minLength="2" maxLength="160" /></label>
            <label>Razão social<input name="legal_name" maxLength="200" /></label>
            <label>CNPJ<input name="cnpj" inputMode="numeric" placeholder="00.000.000/0000-00" required /></label>
            <label>E-mail do administrador<input name="email" type="email" required autoComplete="off" /></label>
            <label>Senha inicial (mínimo 8 caracteres)<input name="password" type="password" required minLength="8" autoComplete="new-password" /></label>
            <label>WhatsApp da loja<input name="phone" type="tel" /></label>
            <label>Endereço comercial<input name="business_address" /></label>
            {error && <p className="form-error">{error}</p>}
            <button className="button primary full" disabled={loading}>
              {loading ? "Cadastrando empresa..." : "Cadastrar empresa e administrador"}
            </button>
          </>
        ) : (
          <>
            <p className="eyebrow">CADASTRO CONCLUÍDO</p>
            <h1>{company.store_name}</h1>
            <p>A empresa foi cadastrada e seu banco de dados foi provisionado.</p>
            <div className="registration-summary">
              <p><strong>CNPJ:</strong> {company.cnpj}</p>
              <p><strong>Administrador:</strong> {company.email}</p>
              <p>Entregue ao administrador o CNPJ, o e-mail e a senha inicial definidos no cadastro.</p>
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
