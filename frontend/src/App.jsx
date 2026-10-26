import { useEffect, useMemo, useState } from "react";
import { api, getTenantCnpj, mediaUrl, uploadImage } from "./lib/api.js";
import { useAuth } from "./context/AuthContext.jsx";
import { useCart } from "./context/CartContext.jsx";
import CompanyRegistration from "./pages/CompanyRegistration.jsx";

const basePath = import.meta.env.BASE_URL;
const siteUrl = (path = "") => {
  const cnpj = getTenantCnpj();
  const query = cnpj ? `?cnpj=${encodeURIComponent(cnpj)}` : "";
  return `${basePath}${path.replace(/^\/+/, "")}${query}`;
};
const appPath = window.location.pathname.startsWith(basePath)
  ? `/${window.location.pathname.slice(basePath.length)}`
  : window.location.pathname;
const formatBRL = (value) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));
const errorText = (error) =>
  error.response?.data?.detail || "Não foi possível concluir a operação. Tente novamente.";

function Storefront() {
  const { items: cart, add, setQty, remove, clear, count: cartCount, total } = useCart();
  const [products, setProducts] = useState([]);
  const [settings, setSettings] = useState({});
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("Todos");
  const [selected, setSelected] = useState(null);
  const [quantity, setQuantity] = useState(1);
  const [cartOpen, setCartOpen] = useState(false);
  const [checkout, setCheckout] = useState(false);
  const [order, setOrder] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refreshProducts = async () => {
    const { data } = await api.get("/products");
    setProducts(data);
  };

  useEffect(() => {
    if (!getTenantCnpj()) {
      setMessage("Acesse a vitrine pelo link da empresa, com o CNPJ após ?cnpj=.");
      return;
    }
    Promise.all([refreshProducts(), api.get("/settings").then(({ data }) => setSettings(data))]).catch((error) =>
      setMessage(errorText(error)),
    );
  }, []);

  const categories = useMemo(
    () => ["Todos", ...new Set(products.map((product) => product.category || "Geral"))],
    [products],
  );
  const visibleProducts = products.filter(
    (product) =>
      (category === "Todos" || product.category === category) &&
      `${product.name} ${product.description} ${product.code}`.toLowerCase().includes(query.toLowerCase()),
  );
  const addToCart = (product, amount, variation = product.variation || "") => {
    add(product, amount, variation);
    setSelected(null);
    setMessage("Produto adicionado ao carrinho.");
  };

  const submitOrder = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const customer = Object.fromEntries(form.entries());
    setBusy(true);
    setMessage("");
    try {
      const { data } = await api.post("/orders", {
        customer,
        items: cart.map((item) => ({ product_id: item.product_id, quantity: item.quantity, variation: item.variation })),
      });
      setOrder(data);
      clear();
      setCheckout(false);
      await refreshProducts();
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  const whatsappUrl = (currentOrder) => {
    const detail = currentOrder.items
      .map((item) => `• ${item.name} x${item.quantity} — ${formatBRL(item.subtotal)}`)
      .join("\n");
    const customer = currentOrder.customer;
    const text = [
      settings.whatsapp_message || "Olá! Segue o resumo do seu pedido:",
      `Loja: ${settings.store_name || "Vitrine Virtual"}`,
      `Cliente: ${customer.name} | ${customer.phone}`,
      `Endereço: ${customer.address}, ${customer.neighborhood} - ${customer.city}`,
      detail,
      "Pagamento: na entrega",
      `Total: ${formatBRL(currentOrder.total)}`,
    ].join("\n");
    return `https://wa.me/${(settings.phone || "").replace(/\D/g, "")}?text=${encodeURIComponent(text)}`;
  };

  return (
    <main className="store">
      <header className="store-header">
        <a className="brand" data-testid="storefront-nav-logo" href={siteUrl()}>
          {settings.logo_url ? <img src={mediaUrl(settings.logo_url)} alt="" /> : <span className="brand-mark">V</span>}
          <span>{settings.store_name || "Vitrine Virtual"}<small>feito para você</small></span>
        </a>
        <label className="search">
          <span aria-hidden="true">⌕</span>
          <input data-testid="storefront-search-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar produtos..." />
        </label>
        <div className="header-actions">
          <a className="admin-link" href={siteUrl("admin")}>Acesso admin</a>
          <button className="cart-trigger" data-testid="storefront-cart-button" onClick={() => setCartOpen(true)}>
            Sacola <span className="cart-badge" data-testid="storefront-cart-count-badge">{cartCount}</span>
          </button>
        </div>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">SELEÇÃO ESPECIAL</p>
          <h1>Pequenos detalhes,<br /><em>grandes momentos.</em></h1>
          <p>Uma seleção cuidadosa de produtos para trazer mais beleza e aconchego ao seu dia.</p>
          <a className="button primary" href={`${siteUrl()}#produtos`}>Explorar vitrine <span>→</span></a>
        </div>
        <div className="hero-art" role="img" aria-label="Produtos artesanais cuidadosamente selecionados">
          <div className="hero-note">feito com<br /><strong>carinho</strong></div>
        </div>
      </section>

      <section className="catalog" id="produtos">
        <div className="section-heading">
          <div><p className="eyebrow">NOSSA VITRINE</p><h2>Encontre algo especial</h2></div>
          <span>{visibleProducts.length} produtos</span>
        </div>
        <nav className="category-list" aria-label="Categorias">
          {categories.map((item) => (
            <button className={category === item ? "category active" : "category"} key={item} onClick={() => setCategory(item)}>{item}</button>
          ))}
        </nav>
        {message && <div className="notice" role="status">{message}<button onClick={() => setMessage("")} aria-label="Fechar">×</button></div>}
        {visibleProducts.length ? (
          <div className="product-grid">
            {visibleProducts.map((product) => (
              <article className="product-card" data-testid={`product-card-${product.id}`} key={product.id} onClick={() => { setSelected(product); setQuantity(1); }}>
                <div className="product-image">
                  {product.image_url ? <img src={mediaUrl(product.image_url)} alt={product.name} /> : <div className="image-placeholder">✳</div>}
                  <span className="stock-tag">{product.stock < 5 ? `Últimas ${product.stock}` : "Em estoque"}</span>
                </div>
                <div className="product-info">
                  <p className="product-category">{product.category || "Geral"}</p>
                  <h3>{product.name}</h3>
                  <p className="product-description">{product.description || "Um detalhe especial para o seu dia."}</p>
                  <div className="product-bottom"><strong>{formatBRL(product.price)}</strong><button data-testid={`product-card-add-button-${product.id}`} aria-label={`Adicionar ${product.name}`} onClick={(event) => { event.stopPropagation(); setSelected(product); setQuantity(1); }}>+</button></div>
                </div>
              </article>
            ))}
          </div>
        ) : <div className="empty-state"><span>✳</span><h3>Nenhum produto por aqui ainda</h3><p>Volte em breve para conferir as novidades.</p></div>}
      </section>

      <footer className="store-footer"><span>{settings.store_name || "Vitrine Virtual"}</span><span>Uma experiência de compra simples e especial.</span></footer>

      {selected && <div className="overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelected(null); }}>
        <section className="dialog product-dialog" role="dialog" aria-modal="true" aria-labelledby="quantity-modal-title">
          <button className="close" onClick={() => setSelected(null)} aria-label="Fechar">×</button>
          <div className="dialog-image">{selected.image_url ? <img src={mediaUrl(selected.image_url)} alt={selected.name} /> : <div className="image-placeholder">✳</div>}</div>
          <div className="dialog-body">
            <p className="eyebrow">{selected.category || "GERAL"}</p><h2 id="quantity-modal-title" data-testid="quantity-modal-title">{selected.name}</h2>
            <p className="product-description">{selected.description}</p>
            {selected.variation && <p className="variation">Variação: {selected.variation}</p>}
            <strong className="dialog-price">{formatBRL(selected.price)}</strong>
            <div className="quantity-row">
              <button data-testid="quantity-modal-minus-btn" onClick={() => setQuantity((value) => Math.max(1, value - 1))} aria-label="Diminuir quantidade">−</button>
              <span>{quantity}</span>
              <button data-testid="quantity-modal-plus-btn" onClick={() => setQuantity((value) => Math.min(selected.stock, value + 1))} aria-label="Aumentar quantidade">+</button>
              <small>{selected.stock} disponíveis</small>
            </div>
            <button className="button primary full" data-testid="quantity-modal-confirm-btn" onClick={() => addToCart(selected, quantity)}>Adicionar ao carrinho · {formatBRL(selected.price * quantity)}</button>
          </div>
        </section>
      </div>}

      {cartOpen && <div className="overlay drawer-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setCartOpen(false); }}>
        <aside className="cart-drawer" data-testid="cart-drawer-container">
          <div className="drawer-heading"><div><p className="eyebrow">SUA SELEÇÃO</p><h2>Sacola ({cartCount})</h2></div><button className="close" onClick={() => setCartOpen(false)} aria-label="Fechar sacola">×</button></div>
          <div className="cart-lines">
            {cart.map((item) => <div className="cart-line" data-testid={`cart-item-${item.product_id}`} key={`${item.product_id}-${item.variation}`}>
              <div className="cart-line-icon">✳</div><div className="cart-line-info"><strong>{item.name || item.description}</strong>{item.variation && <small>{item.variation}</small>}
                <div className="cart-quantity"><button data-testid={`cart-item-minus-${item.product_id}`} aria-label={`Diminuir ${item.name || item.description}`} onClick={() => setQty(item.product_id, item.quantity - 1, item.variation)}>−</button><span>{item.quantity}</span><button data-testid={`cart-item-plus-${item.product_id}`} aria-label={`Aumentar ${item.name || item.description}`} onClick={() => setQty(item.product_id, item.quantity + 1, item.variation)}>+</button><button className="remove" data-testid={`cart-item-remove-${item.product_id}`} onClick={() => remove(item.product_id, item.variation)}>Remover</button></div>
              </div><strong>{formatBRL(item.price * item.quantity)}</strong>
            </div>)}
            {!cart.length && <div className="empty-state"><span>♡</span><h3>Sua sacola está vazia</h3><p>Descubra algo especial na vitrine.</p></div>}
          </div>
          {cart.length > 0 && <div className="cart-summary"><p><span>Subtotal</span><strong>{formatBRL(total)}</strong></p><small>Entrega combinada após a confirmação do pedido.</small><button className="button primary full" data-testid="cart-checkout-button" onClick={() => { setCartOpen(false); setCheckout(true); }}>Finalizar pedido <span>→</span></button></div>}
        </aside>
      </div>}

      {checkout && <div className="overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setCheckout(false); }}>
        <section className="dialog checkout-dialog" data-testid="checkout-modal-step1" role="dialog" aria-modal="true">
          <button className="close" onClick={() => setCheckout(false)} aria-label="Fechar">×</button>
          <p className="eyebrow">ÚLTIMA ETAPA</p><h2>Para onde enviamos?</h2><p className="dialog-lead">Preencha seus dados para registrar o pedido.</p>
          <form className="form-grid" onSubmit={submitOrder}>
            <label className="span-2">Nome completo<input data-testid="checkout-input-name" name="name" required minLength="2" /></label>
            <label>Telefone / WhatsApp<input data-testid="checkout-input-phone" name="phone" required type="tel" /></label>
            <label>CEP<input name="postal_code" /></label>
            <label className="span-2">Endereço<input data-testid="checkout-input-address" name="address" required /></label>
            <label>Bairro<input name="neighborhood" /></label><label>Cidade<input name="city" /></label>
            <label className="span-2">Observações<textarea name="notes" rows="2" /></label>
            <div className="notice span-2">O pagamento será feito na entrega.</div>
            <div className="span-2 checkout-total"><span>Total do pedido</span><strong>{formatBRL(total)}</strong></div>
            {message && <p className="form-error span-2">{message}</p>}
            <button className="button primary full span-2" data-testid="checkout-submit-button" disabled={busy}>{busy ? "Registrando pedido..." : "Confirmar pedido"}</button>
          </form>
        </section>
      </div>}

      {order && <div className="overlay">
        <section className="dialog order-dialog" role="dialog" aria-modal="true">
          <button className="close" onClick={() => setOrder(null)} aria-label="Fechar">×</button>
          <div className="success-mark">✓</div><p className="eyebrow">PEDIDO REGISTRADO</p><h2>Obrigado, {order.customer.name.split(" ")[0]}!</h2>
          <p className="dialog-lead">Pedido #{order.id.slice(0, 8)} · {formatBRL(order.total)}</p>
          <p className="dialog-lead">O pagamento será feito na entrega, diretamente ao entregador.</p>
          <a className="button whatsapp full" data-testid="order-whatsapp-button" href={whatsappUrl(order)} target="_blank" rel="noreferrer">Enviar resumo pelo WhatsApp</a>
        </section>
      </div>}
    </main>
  );
}

function Admin() {
  const { user, login: authenticate, logout: endSession } = useAuth();
  const [tab, setTab] = useState("products");
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [settings, setSettings] = useState({});
  const [editing, setEditing] = useState(null);
  const [customerDialog, setCustomerDialog] = useState(false);
  const [users, setUsers] = useState([]);
  const [userDialog, setUserDialog] = useState(false);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  const loadAdminData = async () => {
    const [p, o, c, s] = await Promise.all([
      api.get("/admin/products"), api.get("/admin/orders"), api.get("/admin/customers"), api.get("/admin/settings"),
    ]);
    setProducts(p.data); setOrders(o.data); setCustomers(c.data); setSettings(s.data);
  };
  useEffect(() => {
    if (user === null) return;
    if (user === false) {
      setLoading(false);
      return;
    }
    loadAdminData()
      .catch((failure) => setError(errorText(failure)))
      .finally(() => setLoading(false));
  }, [user]);

  const login = async (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.currentTarget).entries());
    setLoading(true);
    try { await authenticate(body.cnpj, body.email, body.password); setError(""); }
    catch (failure) { setError(errorText(failure)); setLoading(false); }
  };
  const saveProduct = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const data = Object.fromEntries(form.entries());
    data.price = Number(data.price); data.cost_price = Number(data.cost_price || 0); data.stock = Number(data.stock);
    data.active = form.get("active") === "on";
    try {
      if (editing?.id) await api.put(`/admin/products/${editing.id}`, data);
      else await api.post("/admin/products", data);
      setEditing(null); setNotice("Produto salvo com sucesso."); await loadAdminData();
    } catch (failure) { setError(errorText(failure)); }
  };
  const saveSettings = async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    data.free_delivery_minimum = Number(data.free_delivery_minimum || 0);
    try { await api.put("/admin/settings", data); setNotice("Configurações atualizadas."); await loadAdminData(); }
    catch (failure) { setError(errorText(failure)); }
  };
  const updateStatus = async (orderId, status) => {
    try { await api.patch(`/admin/orders/${orderId}`, { status }); await loadAdminData(); }
    catch (failure) { setError(errorText(failure)); }
  };
  const updatePaymentStatus = async (orderId, payment_status) => {
    try { await api.patch(`/admin/orders/${orderId}`, { payment_status }); await loadAdminData(); }
    catch (failure) { setError(errorText(failure)); }
  };
  const saveCustomer = async (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const customer = Object.fromEntries(formData.entries());
    try {
      await api.post("/admin/customers", customer);
      setCustomerDialog(false);
      setNotice("Cliente cadastrado.");
      await loadAdminData();
    } catch (failure) { setError(errorText(failure)); }
  };
  const removeCustomer = async (customer) => {
    if (!window.confirm(`Remover ${customer.name} da lista de clientes? O histórico dos pedidos será mantido.`)) return;
    try {
      await api.delete(`/admin/customers/${customer.id}`);
      setNotice("Cliente removido. O histórico dos pedidos foi mantido.");
      await loadAdminData();
    } catch (failure) { setError(errorText(failure)); }
  };
  const openUsers = async () => {
    setTab("users");
    setEditing(null);
    try {
      const { data } = await api.get("/admin/users");
      setUsers(data);
    } catch (failure) { setError(errorText(failure)); }
  };
  const saveUser = async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await api.post("/admin/users", data);
      setUserDialog(false);
      setNotice("Usuário operador cadastrado.");
      const response = await api.get("/admin/users");
      setUsers(response.data);
    } catch (failure) { setError(errorText(failure)); }
  };
  const removeUser = async (operator) => {
    if (!window.confirm(`Remover o acesso de ${operator.name || operator.username}?`)) return;
    try {
      await api.delete(`/admin/users/${operator.id}`);
      setUsers((current) => current.filter((item) => item.id !== operator.id));
      setNotice("Acesso do usuário removido.");
    } catch (failure) { setError(errorText(failure)); }
  };
  const cancelOrder = async (order) => {
    if (!window.confirm("Cancelar este pedido? O estoque será reposto e o registro permanecerá no histórico.")) return;
    try {
      await api.delete(`/admin/orders/${order.id}`);
      setNotice("Pedido cancelado e estoque reposto.");
      await loadAdminData();
    } catch (failure) { setError(errorText(failure)); }
  };
  const orderWhatsAppUrl = (order) => {
    const customer = order.customer || {};
    const lines = order.items.map((item) => {
      const name = item.name || item.description || "Produto";
      const variation = item.variation || item.grade;
      return `• ${item.quantity}x ${name}${variation ? ` (${variation})` : ""} — ${formatBRL(item.subtotal ?? item.unit_price * item.quantity)}`;
    }).join("\n");
    const text = [
      settings.whatsapp_message || "Olá! Segue o resumo do seu pedido:",
      `Loja: ${settings.store_name || "Vitrine Virtual"}`,
      `Cliente: ${customer.name || ""} | ${customer.phone || ""}`,
      `Endereço: ${[customer.address, customer.neighborhood || customer.district, customer.city, customer.postal_code || customer.cep].filter(Boolean).join(", ")}`,
      lines,
      `Pagamento: ${order.payment_status === "Pago na entrega" ? "Pago na entrega" : "A receber na entrega"}`,
      `Total: ${formatBRL(order.total)}`,
    ].join("\n");
    const phone = (settings.phone || "").replace(/\D/g, "");
    return phone ? `https://wa.me/${phone}?text=${encodeURIComponent(text)}` : "";
  };
  const removeProduct = async (id) => {
    if (!window.confirm("Deseja realmente excluir este produto?")) return;
    try { await api.delete(`/admin/products/${id}`); setNotice("Produto removido."); await loadAdminData(); }
    catch (failure) { setError(errorText(failure)); }
  };
  const handleImageUpload = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploadingImage(true);
    setError("");
    try {
      const uploaded = await uploadImage(file);
      if (tab === "products" && editing) {
        setEditing((current) => ({ ...current, image_url: uploaded.url }));
      } else if (tab === "settings") {
        setSettings((current) => ({ ...current, logo_url: uploaded.url }));
      } else {
        throw new Error("Selecione um produto ou as configurações da empresa antes do upload.");
      }
      setNotice("Imagem enviada e armazenada no MongoDB.");
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      event.target.value = "";
      setUploadingImage(false);
    }
  };
  const logout = async () => {
    try {
      await endSession();
    } catch (failure) {
      setError(errorText(failure));
    }
  };

  if (loading || user === null) return <div className="admin-loading">Carregando painel...</div>;
  if (!user) return <main className="login-page">
    <a className="brand" href={siteUrl()}><span className="brand-mark">V</span><span>Vitrine Virtual<small>Painel administrativo</small></span></a>
    <form className="login-card" onSubmit={login}>
      <p className="eyebrow">ÁREA RESTRITA</p><h1>Bem-vindo de volta</h1><p>Acesse para gerenciar sua loja.</p>
      <label>CNPJ da empresa<input data-testid="admin-login-cnpj-input" name="cnpj" required inputMode="numeric" defaultValue={getTenantCnpj()} /></label>
      <label>Usuário ou e-mail<input data-testid="admin-login-email-input" name="email" required autoComplete="username" /></label>
      <label>Senha<input data-testid="admin-login-password-input" name="password" type="password" required autoComplete="current-password" /></label>
      {error && <p className="form-error">{error}</p>}
      <button className="button primary full" data-testid="admin-login-submit-btn">Entrar no painel</button>
      <a href={siteUrl()} className="back-link">← Voltar para a vitrine</a>
    </form>
  </main>;

  const currentOrder = orders.find((item) => item.id === new URLSearchParams(window.location.search).get("print"));
  if (currentOrder) return <main className="romaneio" id="romaneio">
    <button className="button primary print-button" data-testid="admin-romaneio-print-btn" onClick={() => window.print()}>Imprimir romaneio</button>
    <h1>{settings.store_name || "Vitrine Virtual"}</h1><h2>Romaneio de entrega</h2>
    <p><strong>Pedido:</strong> {currentOrder.id.slice(0, 8)} · {new Date(currentOrder.created_at).toLocaleString("pt-BR")}</p>
    <section><h3>Cliente e endereço</h3><p>{currentOrder.customer.name} · {currentOrder.customer.phone}</p><p>{currentOrder.customer.address}, {currentOrder.customer.neighborhood} — {currentOrder.customer.city} {currentOrder.customer.postal_code}</p><p>Observações / rota: {currentOrder.customer.notes || "________________________________________"}</p></section>
    <section><h3>Itens para separar</h3>{currentOrder.items.map((item) => <p key={item.product_id}>□ {item.quantity} × {item.name} {item.variation} — {formatBRL(item.subtotal)}</p>)}<h3>Total: {formatBRL(currentOrder.total)}</h3></section>
    <p className="signature">Assinatura do entregador: ____________________________________</p>
  </main>;

  const nav = [
    ["products", "Produtos", "admin-nav-products-tab"],
    ["customers", "Clientes", "admin-nav-customers-tab"],
    ["orders", "Pedidos", "admin-nav-orders-tab"],
    ...(user.role === "admin" ? [["users", "Usuários", "admin-nav-users-tab"]] : []),
    ["settings", "Configurações", "admin-nav-settings-tab"],
  ];
  return <div className="admin-shell">
    <aside className="admin-sidebar">
      <a className="brand" href={siteUrl()}><span className="brand-mark">V</span><span>Vitrine Virtual<small>PAINEL DA LOJA</small></span></a>
      <nav>{nav.map(([key, label, testId]) => <button key={key} data-testid={testId} className={tab === key ? "admin-nav active" : "admin-nav"} onClick={() => { if (key === "users") { void openUsers(); return; } setTab(key); setEditing(null); }}>{label}</button>)}</nav>
      <a className="view-store" href={siteUrl()}>↗ Ver vitrine pública</a>
      <button className="logout" onClick={logout}>Sair da conta</button>
    </aside>
    <main className="admin-main">
      <header className="admin-topbar"><span>Gestão da loja / <strong>{nav.find(([key]) => key === tab)?.[1]}</strong></span><span className="admin-user">{user.name}</span></header>
      <section className="admin-content">
        {notice && <div className="notice">{notice}<button onClick={() => setNotice("")}>×</button></div>}
        {error && <div className="notice error-notice">{error}<button onClick={() => setError("")}>×</button></div>}
        {tab === "products" && <>
          <div className="admin-heading"><div><p className="eyebrow">CATÁLOGO</p><h1>Produtos</h1><p>Gerencie o catálogo e o estoque da sua vitrine.</p></div>
            <button className="button primary" data-testid="admin-product-add-button" onClick={() => setEditing({})}>+ Novo produto</button></div>
          {editing && <form className="admin-form product-form" onSubmit={saveProduct}>
            <div className="form-title"><h2>{editing.id ? "Editar produto" : "Novo produto"}</h2><button type="button" className="close" onClick={() => setEditing(null)}>×</button></div>
            <div className="form-grid">
              <label>Código<input name="code" defaultValue={editing.code || ""} /></label><label className="span-2">Nome do produto<input name="name" required defaultValue={editing.name || ""} /></label>
              <label>Categoria<input name="category" defaultValue={editing.category || "Geral"} /></label>
              <label>Preço de venda (R$)<input name="price" type="number" min="0.01" step="0.01" required defaultValue={editing.price ?? ""} /></label>
              <label>Preço de custo (R$)<input name="cost_price" type="number" min="0" step="0.01" defaultValue={editing.cost_price ?? 0} /></label>
              <label>Estoque<input name="stock" type="number" min="0" required defaultValue={editing.stock ?? 0} /></label>
              <label>Unidade<select name="unit" defaultValue={editing.unit || "UN"}><option>UN</option><option>KG</option><option>CX</option><option>PCT</option></select></label>
              <label>Grade / variação<input name="variation" defaultValue={editing.variation || ""} /></label>
              <label className="span-2">URL da imagem<input name="image_url" type="url" value={editing.image_url || ""} onChange={(event) => setEditing((current) => ({ ...current, image_url: event.target.value }))} /></label>
              <label className="span-2">Enviar imagem para o MongoDB<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={handleImageUpload} disabled={uploadingImage} />{uploadingImage && <small>Enviando imagem...</small>}{editing.image_url && <img className="admin-image-preview" src={mediaUrl(editing.image_url)} alt="Prévia do produto" />}</label>
              <label className="span-2">Descrição<textarea name="description" rows="2" defaultValue={editing.description || ""} /></label>
              <label className="checkbox-label span-2"><input name="active" type="checkbox" defaultChecked={editing.active !== false} /> Produto ativo na vitrine</label>
            </div>
            <div className="form-actions"><button type="button" className="button secondary" onClick={() => setEditing(null)}>Cancelar</button><button className="button primary" data-testid="admin-product-form-submit">Salvar produto</button></div>
          </form>}
          <div className="table-wrap"><table><thead><tr><th>Produto</th><th>Código</th><th>Preço</th><th>Estoque</th><th>Status</th><th></th></tr></thead><tbody>
            {products.map((product) => <tr data-testid={`admin-product-row-${product.id}`} key={product.id}><td><strong>{product.name}</strong><small>{product.category}</small></td><td>{product.code || "—"}</td><td>{formatBRL(product.price)}</td><td>{product.stock} {product.unit}</td><td><span className={product.active && product.stock ? "status-pill status-ok" : "status-pill status-off"}>{product.active && product.stock ? "Ativo" : "Indisponível"}</span></td><td className="table-actions"><button onClick={() => setEditing(product)}>Editar</button><button onClick={() => removeProduct(product.id)}>Excluir</button></td></tr>)}
            {!products.length && <tr><td colSpan="6" className="table-empty">Nenhum produto cadastrado.</td></tr>}
          </tbody></table></div>
        </>}
        {tab === "customers" && <><div className="admin-heading"><div><p className="eyebrow">RELACIONAMENTO</p><h1>Clientes</h1><p>{customers.length} clientes cadastrados</p></div><button className="button primary" data-testid="admin-customer-add-button" onClick={() => setCustomerDialog(true)}>+ Novo cliente</button></div>
          <div className="table-wrap"><table><thead><tr><th>Nome</th><th>WhatsApp</th><th>Endereço</th><th>Pedidos</th><th></th></tr></thead><tbody>
            {customers.map((customer) => <tr data-testid={`admin-customer-row-${customer.id}`} key={customer.id}><td><strong>{customer.name}</strong></td><td>{customer.phone || "—"}</td><td>{[customer.address, customer.neighborhood || customer.district, customer.city, customer.postal_code || customer.cep].filter(Boolean).join(", ") || "—"}</td><td>{customer.order_count ?? customer.orders_count ?? 0}</td><td className="table-actions">{customer.phone && <a className="table-link" href={`https://wa.me/${customer.phone.replace(/\D/g, "")}`} target="_blank" rel="noreferrer">WhatsApp ↗</a>}<button onClick={() => removeCustomer(customer)}>Remover</button></td></tr>)}
            {!customers.length && <tr><td colSpan="5" className="table-empty">Nenhum cliente cadastrado.</td></tr>}
          </tbody></table></div>
          {customerDialog && <div className="overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setCustomerDialog(false); }}><section className="dialog checkout-dialog" role="dialog" aria-modal="true">
            <button className="close" onClick={() => setCustomerDialog(false)} aria-label="Fechar">×</button><p className="eyebrow">RELACIONAMENTO</p><h2>Novo cliente</h2>
            <form className="form-grid" onSubmit={saveCustomer}>
              <label className="span-2">Nome completo<input name="name" required minLength="2" /></label>
              <label>WhatsApp<input name="phone" type="tel" /></label><label>CEP<input name="postal_code" /></label>
              <label className="span-2">Endereço<input name="address" /></label>
              <label>Bairro<input name="neighborhood" /></label><label>Cidade<input name="city" /></label>
              <label className="span-2">Observações<textarea name="notes" rows="2" /></label>
              <button className="button primary full span-2">Salvar cliente</button>
            </form>
          </section></div>}
        </>}
        {tab === "orders" && <><div className="admin-heading"><div><p className="eyebrow">VENDAS</p><h1>Pedidos & romaneio</h1><p>Acompanhe os pedidos e organize as entregas.</p></div></div>
          <div className="table-wrap"><table><thead><tr><th>Pedido</th><th>Cliente</th><th>Data</th><th>Total</th><th>Status</th><th>Pagamento</th><th>Ações</th></tr></thead><tbody>
            {orders.map((item) => <tr data-testid={`admin-order-row-${item.id}`} key={item.id}><td>#{item.id.slice(0, 8)}<small>{item.items.length} itens</small></td><td><strong>{item.customer.name}</strong><small>{item.customer.phone}</small></td><td>{new Date(item.created_at).toLocaleDateString("pt-BR")}</td><td>{formatBRL(item.total)}</td><td><select className="status-select" aria-label={`Status do pedido ${item.id}`} value={item.status} disabled={item.status === "Cancelado"} onChange={(event) => updateStatus(item.id, event.target.value)}>{["Pendente", "Confirmado", "Em Separação", "Entregue", ...(item.status === "Pendente PIX" ? ["Pendente PIX"] : []), ...(item.status === "Cancelado" ? ["Cancelado"] : [])].map((status) => <option key={status}>{status}</option>)}</select></td><td><select className="status-select" aria-label={`Status do pagamento ${item.id}`} value={item.payment_status || "A receber"} disabled={item.status === "Cancelado"} onChange={(event) => updatePaymentStatus(item.id, event.target.value)}>{["A receber", "Pago na entrega"].map((status) => <option key={status}>{status}</option>)}</select></td><td className="table-actions"><a className="table-link" href={`${siteUrl("admin")}?print=${item.id}`} target="_blank" rel="noreferrer">Romaneio ↗</a>{item.status !== "Cancelado" && <><a className="table-link" href={orderWhatsAppUrl(item) || undefined} target="_blank" rel="noreferrer" aria-disabled={!settings.phone} onClick={(event) => { if (!settings.phone) { event.preventDefault(); setError("Configure o WhatsApp da empresa nas configurações."); } }}>WhatsApp ↗</a><button disabled={item.payment_status === "Pago na entrega"} title={item.payment_status === "Pago na entrega" ? "Regularize o pagamento antes de cancelar." : undefined} onClick={() => cancelOrder(item)}>Cancelar</button></>}</td></tr>)}
            {!orders.length && <tr><td colSpan="7" className="table-empty">Nenhum pedido recebido.</td></tr>}
          </tbody></table></div>
        </>}
        {tab === "users" && user.role === "admin" && <>
          <div className="admin-heading"><div><p className="eyebrow">ACESSO AO PAINEL</p><h1>Usuários operadores</h1><p>Cadastre acessos para sua equipe. Apenas administradores podem gerenciar usuários.</p></div><button className="button primary" data-testid="admin-user-add-button" onClick={() => setUserDialog(true)}>+ Novo usuário</button></div>
          <div className="table-wrap"><table><thead><tr><th>Usuário</th><th>Nome</th><th>Função</th><th></th></tr></thead><tbody>
            {users.map((operator) => <tr data-testid={`admin-user-row-${operator.id}`} key={operator.id}><td>{operator.username || operator.email}</td><td><strong>{operator.name}</strong></td><td><span className={`status-pill ${operator.role === "admin" ? "status-ok" : "status-off"}`}>{operator.role === "admin" ? "Administrador" : "Operador"}</span></td><td className="table-actions">{operator.role !== "admin" && <button onClick={() => removeUser(operator)}>Remover acesso</button>}</td></tr>)}
            {!users.length && <tr><td colSpan="4" className="table-empty">Nenhum usuário cadastrado.</td></tr>}
          </tbody></table></div>
          {userDialog && <div className="overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) setUserDialog(false); }}><section className="dialog checkout-dialog" role="dialog" aria-modal="true">
            <button className="close" onClick={() => setUserDialog(false)} aria-label="Fechar">×</button><p className="eyebrow">ACESSO AO PAINEL</p><h2>Novo operador</h2><p className="dialog-lead">O usuário poderá acessar os produtos, clientes, pedidos e configurações.</p>
            <form className="form-grid" onSubmit={saveUser}>
              <label className="span-2">Usuário / e-mail<input name="username" required minLength="3" autoComplete="username" /></label>
              <label className="span-2">Nome<input name="name" /></label>
              <label className="span-2">Senha (mínimo 8 caracteres)<input name="password" type="password" required minLength="8" autoComplete="new-password" /></label>
              <button className="button primary full span-2" data-testid="admin-user-form-submit">Cadastrar operador</button>
            </form>
          </section></div>}
        </>}
        {tab === "settings" && <><div className="admin-heading"><div><p className="eyebrow">SUA MARCA</p><h1>Configurações da empresa</h1><p>Essas informações aparecem na vitrine e no checkout.</p></div></div>
          <form className="admin-form settings-form" onSubmit={saveSettings}><div className="form-grid">
            <label className="span-2">Nome da loja<input name="store_name" required defaultValue={settings.store_name} /></label>
            <label>Razão social / titular<input name="legal_name" defaultValue={settings.legal_name} /></label><label>CPF / CNPJ<input name="document" defaultValue={settings.document} /></label>
            <label className="span-2">WhatsApp da empresa<input name="phone" defaultValue={settings.phone} /></label>
            <label className="span-2">URL da logomarca<input name="logo_url" type="url" value={settings.logo_url || ""} onChange={(event) => setSettings((current) => ({ ...current, logo_url: event.target.value }))} /></label>
            <label className="span-2">Enviar logomarca para o MongoDB<input type="file" accept="image/jpeg,image/png,image/webp,image/gif" onChange={handleImageUpload} disabled={uploadingImage} />{uploadingImage && <small>Enviando imagem...</small>}{settings.logo_url && <img className="admin-image-preview logo-preview" src={mediaUrl(settings.logo_url)} alt="Prévia da logomarca" />}</label>
            <label className="span-2">Endereço comercial<input name="business_address" defaultValue={settings.business_address} /></label>
            <label className="span-2">Mensagem para pedidos<input name="whatsapp_message" defaultValue={settings.whatsapp_message} /></label>
            <label>Entrega grátis acima de (R$)<input name="free_delivery_minimum" type="number" min="0" step="0.01" defaultValue={settings.free_delivery_minimum} /></label>
          </div><div className="form-actions"><button className="button primary">Salvar configurações</button></div></form>
        </>}
      </section>
    </main>
  </div>;
}

export default function App() {
  if (appPath === "/cadastro") return <CompanyRegistration />;
  if (appPath.startsWith("/admin")) return <Admin />;
  return <Storefront />;
}
