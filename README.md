# Vitrine Virtual

Aplicação de loja virtual e painel administrativo em português (Brasil).

## Requisitos

- Python 3.10+
- Node.js 20.19+ ou 22.12+
- MongoDB acessível pela URL configurada

## Configuração e execução

1. Copie `backend/.env.example` para `backend/.env` e configure MongoDB, uma chave JWT aleatória e `PLATFORM_SETUP_SECRET`, um código privado que somente o proprietário da plataforma deve conhecer. Gere um valor forte, por exemplo com `python -c "import secrets; print(secrets.token_urlsafe(48))"`, e substitua o texto de exemplo. Configure também `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` e `SMTP_FROM` com os dados do seu provedor de e-mail; use `SMTP_USE_SSL=true` para SSL direto (normalmente porta 465) ou `false` para STARTTLS (normalmente porta 587). O cadastro não cria a empresa se o envio de convites não estiver configurado.
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
- Carrinho persistido no navegador, checkout de cliente, baixa de estoque e pagamento na entrega.
- Área administrativa para produtos, clientes, pedidos, configurações, usuários operadores e romaneio imprimível.
- Upload de imagens de até 5 MB (JPEG, PNG, WebP ou GIF), armazenado no MongoDB GridFS.
- Cadastro de empresas protegido pelo código mestre no backend; cada empresa recebe um banco MongoDB próprio, identificado pelo CNPJ. O administrador recebe um convite de uso único, válido por 24 horas, para definir a própria senha; o responsável pela plataforma pode reenviar o convite pelo painel master.
- Usuários operadores são criados somente pelo administrador da empresa; não há cadastro público de administradores.
- Cancelamento de pedidos mantém o registro no histórico e repõe o estoque reservado.
- Não há integração com provedor de pagamentos: o cliente paga ao receber o pedido, e o administrador pode registrar no painel quando o pagamento for recebido.

Em produção, use HTTPS, configure `COOKIE_SECURE=true`, defina `CORS_ORIGINS` com a origem exata do frontend e não reutilize credenciais de desenvolvimento.

Para Gmail/Google Workspace, use `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USE_SSL=false`, o endereço Gmail em `SMTP_USERNAME` e `SMTP_FROM`, e uma App Password em `SMTP_PASSWORD` (não a senha normal da conta). A conta precisa ter a verificação em duas etapas ativada. Nunca envie ou armazene a App Password no repositório.

## Hospedar a API no Render e o banco no MongoDB Atlas

O arquivo `render.yaml` configura a API FastAPI no plano gratuito do Render. O banco MongoDB e as imagens do GridFS ficam no MongoDB Atlas.

1. Crie uma conta no MongoDB Atlas, crie um cluster e um usuário de banco com senha forte. Em **Network Access**, permita somente os endereços de saída/IPs ou a rede privada configurada para o serviço no Render; não use `0.0.0.0/0`. Proteja o acesso com uma senha exclusiva e não compartilhe a URL do banco.
2. No Atlas, copie a connection string `mongodb+srv://...` e substitua o marcador de senha pelo segredo do usuário criado.
3. No Render, escolha **New → Blueprint**, conecte o repositório `luiskingofgamelcs-lang/Loja-Virtual` e selecione a branch `main`. O Render encontrará `render.yaml`; informe a connection string em `MONGO_URL`, as credenciais SMTP do provedor em `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` e `SMTP_FROM`, e crie o serviço. Ajuste `SMTP_PORT`/`SMTP_USE_SSL` conforme o provedor. `JWT_SECRET` e `PLATFORM_SETUP_SECRET` serão gerados pelo Render e devem permanecer somente no ambiente do serviço.
4. Após o deploy, teste `https://<nome-do-servico>.onrender.com/health`. A resposta esperada é `{"status":"ok"}`. A documentação da API fica em `/docs`.
5. No repositório GitHub, abra **Settings → Secrets and variables → Actions → Variables → New repository variable**. Crie `VITE_BACKEND_URL` com a URL base terminada em `/api`, por exemplo `https://<nome-do-servico>.onrender.com/api`. Não acrescente `/` ao final.
6. Em **Actions**, abra `Deploy frontend to GitHub Pages` e escolha **Run workflow** para reconstruir o frontend usando a variável nova. Depois teste o site publicado.
7. Para cadastrar uma empresa, use `/cadastro`, informe o código mestre e o e-mail do administrador. O convite de ativação é enviado pelo SMTP configurado; o administrador cria uma senha exclusiva de pelo menos 12 caracteres no link. Esse link expira em 24 horas e só pode ser usado uma vez.
8. Configure `PLATFORM_ADMIN_EMAIL` e uma senha exclusiva de pelo menos 12 caracteres em `PLATFORM_ADMIN_PASSWORD` no ambiente do Render; acesse `/superadmin` para listar, suspender ou reativar empresas e reenviar convites ainda pendentes. A suspensão bloqueia o tenant sem apagar seu banco.
9. Os clientes da loja se cadastram em `/cliente/cadastro?cnpj=<cnpj-da-empresa>` e acessam pedidos e perfil em `/cliente?cnpj=<cnpj-da-empresa>`. As contas ficam em uma coleção separada dentro do banco exclusivo de cada loja; pedidos só aparecem no histórico da conta que os criou autenticada.
10. A vitrine expõe apenas dados de catálogo necessários à compra. Cadastro e login são públicos para permitir acesso, mas pedidos exigem sessão do cliente; rotas administrativas e de perfil também exigem sessão. Respostas da API não são armazenadas em cache, e origens de escrita fora de `CORS_ORIGINS` são recusadas.

O plano gratuito do Render pode suspender o serviço após inatividade, causando demora na primeira chamada. Mantenha as credenciais do MongoDB e os segredos somente nas variáveis privadas do Render.

## Publicação pelo GitHub Pages

O workflow `.github/workflows/pages.yml` compila e publica o frontend no GitHub Pages a cada push para `main`. Em **Settings → Pages**, escolha **GitHub Actions** como fonte de publicação.

Antes da publicação:

1. Envie a branch `main` para o GitHub. Em **Settings → Pages**, selecione **GitHub Actions** como fonte.
2. O workflow publica o frontend mesmo sem API configurada. Sem backend, o site visual abre, mas produtos, login, cadastro, pedidos e imagens servidas pelo servidor não funcionarão.
3. Para habilitar a loja completa, hospede a API FastAPI e o MongoDB em um serviço externo seguindo [as instruções para Render e Atlas](#hospedar-a-api-no-render-e-o-banco-no-mongodb-atlas); configure a variável `VITE_BACKEND_URL` em **Settings → Secrets and variables → Actions → Variables** com a URL da API terminada em `/api` (por exemplo, `https://api.seudominio.com/api`).
4. No ambiente da API, configure `CORS_ORIGINS` com a origem do site Pages (por exemplo, `https://seu-usuario.github.io`, sem o caminho do repositório), `COOKIE_SECURE=true`, `PLATFORM_SETUP_SECRET`, as variáveis SMTP e `FRONTEND_URL` com a URL base do Pages, incluindo o caminho do repositório.
5. Cadastre cada empresa em `/cadastro`. O CNPJ informado cria seu banco e o administrador recebe um convite por e-mail para definir a própria senha; não solicite nem compartilhe a senha do cliente.
6. O link público da vitrine deve incluir o CNPJ da empresa: `https://seu-usuario.github.io/seu-repositorio/?cnpj=12345678000199`. O login também solicita CNPJ e encaminha as chamadas ao banco correspondente.

Se `VITE_BACKEND_URL` não estiver configurada, o workflow emite um aviso e publica somente o frontend estático. As imagens enviadas pelo painel são armazenadas no GridFS do MongoDB da empresa e servidas pela API em `/api/media`. URLs externas existentes continuam aceitas. O segredo de cadastro, os hashes/senhas de administradores, o segredo JWT e as credenciais do MongoDB devem ficar somente no ambiente do servidor da API, nunca em variáveis `VITE_*` ou no repositório.
