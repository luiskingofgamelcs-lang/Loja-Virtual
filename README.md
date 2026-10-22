# Vitrine Virtual

Aplicação de loja virtual e painel administrativo em português (Brasil).

## Requisitos

- Python 3.10+
- Node.js 20.19+ ou 22.12+
- MongoDB acessível pela URL configurada

## Configuração e execução

1. Copie `backend/.env.example` para `backend/.env` e configure MongoDB, uma chave JWT aleatória e `PLATFORM_SETUP_SECRET`, um código privado que somente o proprietário da plataforma deve conhecer. Gere um valor forte, por exemplo com `python -c "import secrets; print(secrets.token_urlsafe(48))"`, e substitua o texto de exemplo. O cadastro de empresas não fica aberto sem esse segredo.
2. Em um terminal, instale as dependências e inicie a API:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   uvicorn server:app --reload
   ```

3. Em outro terminal, instale as dependências e inicie a vitrine:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

   Acesse `http://localhost:5173`. O cadastro reservado ao proprietário fica em `/cadastro`; o administrador da empresa entra em `/admin`. O Vite encaminha `/api` para `http://localhost:8000`. Para outra URL, configure `VITE_BACKEND_URL` no ambiente do frontend como a URL base da API, incluindo `/api`.

## Funcionalidades

- Vitrine pública com busca, categorias e filtro automático de produtos sem estoque.
- Carrinho persistido no navegador, checkout de cliente, baixa de estoque, código PIX copia e cola e QR Code.
- Área administrativa para produtos, clientes, pedidos, configurações, usuários operadores e romaneio imprimível.
- Upload de imagens de até 5 MB (JPEG, PNG, WebP ou GIF), armazenado no MongoDB GridFS.
- Cadastro de empresas protegido pelo código mestre no backend; cada empresa recebe um banco MongoDB próprio, identificado pelo CNPJ.
- Usuários operadores são criados somente pelo administrador da empresa; não há cadastro público de administradores.
- Cancelamento de pedidos mantém o registro no histórico e repõe o estoque reservado.
- PIX é gerado com a chave configurada pela loja. A confirmação do pagamento e a comunicação de pedidos são manuais; não há integração com um provedor de pagamentos.

Em produção, use HTTPS, configure `COOKIE_SECURE=true`, defina `CORS_ORIGINS` com a origem exata do frontend e não reutilize credenciais de desenvolvimento.

## Publicação pelo GitHub Pages

O workflow `.github/workflows/pages.yml` compila e publica o frontend no GitHub Pages a cada push para `main`. Em **Settings → Pages**, escolha **GitHub Actions** como fonte de publicação.

Antes da publicação:

1. Hospede a API FastAPI e o MongoDB em um serviço externo; GitHub Pages hospeda somente arquivos estáticos.
2. Em **Settings → Secrets and variables → Actions → Variables**, crie `VITE_BACKEND_URL` com a URL pública da API, incluindo `/api` (por exemplo, `https://api.seudominio.com/api`).
3. No ambiente da API, configure `CORS_ORIGINS` com a origem do site Pages (por exemplo, `https://seu-usuario.github.io`, sem o caminho do repositório), `COOKIE_SECURE=true` e `PLATFORM_SETUP_SECRET`.
4. Cadastre cada empresa em `/cadastro`. O CNPJ informado cria/seleciona seu banco. Compartilhe com o administrador o CNPJ, e-mail e senha inicial que você definiu.
5. O link público da vitrine deve incluir o CNPJ da empresa: `https://seu-usuario.github.io/seu-repositorio/?cnpj=12345678000199`. O login também solicita CNPJ e encaminha as chamadas ao banco correspondente.

O workflow interrompe o build com uma mensagem explícita enquanto `VITE_BACKEND_URL` não estiver configurada. As imagens enviadas pelo painel são armazenadas no GridFS do MongoDB da empresa e servidas pela API em `/api/media`. URLs externas existentes continuam aceitas. O segredo de cadastro, os hashes/senhas de administradores, o segredo JWT e as credenciais do MongoDB devem ficar somente no ambiente do servidor da API, nunca em variáveis `VITE_*` ou no repositório.
