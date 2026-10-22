import { createContext, useContext, useEffect, useMemo, useState } from "react";

const CartContext = createContext(null);
const STORAGE_KEY = "cart";

function readCart() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    if (!Array.isArray(saved)) throw new TypeError("O conteúdo salvo do carrinho não é uma lista.");
    return saved.filter(
      (item) =>
        item &&
        typeof item.product_id === "string" &&
        Number.isInteger(item.quantity) &&
        item.quantity > 0 &&
        Number.isFinite(Number(item.price)),
    ).map((item) => ({
      ...item,
      name: item.name || item.description,
      variation: item.variation || item.grade || "",
      stock: Number(item.stock ?? Number.MAX_SAFE_INTEGER),
    }));
  } catch (error) {
    console.warn("Carrinho salvo inválido; iniciando um carrinho vazio.", error);
    return [];
  }
}

export const useCart = () => {
  const context = useContext(CartContext);
  if (!context) throw new Error("useCart precisa ser usado dentro de CartProvider.");
  return context;
};

export function CartProvider({ children }) {
  const [items, setItems] = useState(readCart);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  }, [items]);

  const add = (product, quantity, variation = product.variation || product.grade || "") => {
    const productId = String(product.id ?? product.product_id);
    const stock = Number(product.stock ?? product.quantity ?? quantity);
    setItems((previous) => {
      const existing = previous.find(
        (item) => item.product_id === productId && item.variation === variation,
      );
      if (existing) {
        return previous.map((item) =>
          item === existing
            ? { ...item, quantity: Math.min(stock, item.quantity + quantity), stock }
            : item,
        );
      }
      return [
        ...previous,
        {
          product_id: productId,
          name: product.name || product.description,
          description: product.description || product.name,
          price: Number(product.price),
          quantity: Math.min(stock, quantity),
          stock,
          variation,
          grade: product.grade || variation,
          image_url: product.image_url || "",
          unit: product.unit || "UN",
        },
      ];
    });
  };

  const setQty = (productId, quantity, variation = "") => {
    setItems((previous) =>
      previous.map((item) =>
        item.product_id === productId && item.variation === variation
          ? { ...item, quantity: Math.min(item.stock, Math.max(1, quantity)) }
          : item,
      ),
    );
  };

  const remove = (productId, variation = "") => {
    setItems((previous) =>
      previous.filter((item) => item.product_id !== productId || item.variation !== variation),
    );
  };
  const clear = () => setItems([]);
  const count = items.reduce((sum, item) => sum + item.quantity, 0);
  const total = items.reduce((sum, item) => sum + item.price * item.quantity, 0);
  const value = useMemo(
    () => ({ items, add, setQty, remove, clear, count, total }),
    [items, count, total],
  );

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}
