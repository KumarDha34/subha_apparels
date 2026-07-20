/* Garment Management System - core API client
   Handles JWT storage, authenticated fetch with auto-refresh, role-based
   routing to each dashboard, and the shared sidebar/topbar chrome. */

const API_BASE = "/api";

const ROLE_LABELS = {
  ADMIN: "Administrator",
  MERCHANDISE: "Merchandise",
  STORE_MANAGER: "Store Manager",
  CUTTING_SUPERVISOR: "Cutting Supervisor",
  PRODUCTION_SUPERVISOR: "Production Supervisor",
  FINISHING_SUPERVISOR: "Finishing Supervisor",
  ACCOUNTS: "Accounts",
  OPERATOR: "Operator",
};

/* Where each role lands right after login. */
const ROLE_DASHBOARD = {
  ADMIN: "/dashboard/admin/",
  MERCHANDISE: "/dashboard/merchandising/",
  STORE_MANAGER: "/dashboard/store/",
  CUTTING_SUPERVISOR: "/dashboard/cutting/",
  PRODUCTION_SUPERVISOR: "/dashboard/production/",
  FINISHING_SUPERVISOR: "/dashboard/finishing/",
  ACCOUNTS: "/dashboard/accounts/",
  OPERATOR: "/dashboard/operator/",
};

/* Full sidebar menu. Admin sees every item; everyone else sees only the
   item(s) matching their role (plus nothing else - keeps each dashboard
   focused on that department's job). */
const MENU = [
  // ===== Admin sidebar: exactly these, all live from the DB. "Entry"/"Master"
  // items open their functional page (create/manage); the rest are reports. =====
  { key: "kpi", label: "Management KPI Dashboard", href: "/dashboard/kpi/", icon: "\u{1F4C8}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "admin", label: "Overview", href: "/dashboard/admin/", icon: "\u{1F3E0}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "merch-orders", label: "Orders & Products", href: "/merchandising/orders/", icon: "\u{1F4DD}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-product-gallery", label: "Product Gallery", href: "/reports/?key=product-gallery", icon: "\u{1F5BC}\u{FE0F}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-product-overview", label: "Product Overview", href: "/reports/?key=product-overview", icon: "\u{1F455}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "merch-products", label: "Style Master", href: "/merchandising/products/", icon: "\u{1F3F7}\u{FE0F}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "cutting-orders-list", label: "Cutting Entry", href: "/cutting/orders/", icon: "\u{2702}\u{FE0F}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "production-bundle-allocation", label: "Stitching Entry", href: "/production/bundle-allocation/", icon: "\u{1F9F5}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "finishing-operations", label: "Finishing Entry", href: "/finishing/operations/", icon: "\u{2728}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "store-stock", label: "Store Entry", href: "/store/stock/", icon: "\u{1F4E6}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-product-pnl", label: "Product P&L", href: "/reports/?key=product-pnl", icon: "\u{1F4B9}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "production-operators", label: "Operator Overview", href: "/production/operators/", icon: "\u{1F9D1}\u{200D}\u{1F3ED}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-quality-report", label: "Quality Report", href: "/reports/?key=quality-report", icon: "\u{1F50D}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-piece-loss", label: "Piece Loss Tracking", href: "/reports/?key=piece-loss", icon: "\u{1F4C9}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "users", label: "Employee Master", href: "/users/", icon: "\u{1F465}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "finishing-dispatch", label: "Dispatch & Balance", href: "/finishing/dispatch/", icon: "\u{1F69A}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-fabric-wastage", label: "Fabric Wastage", href: "/reports/?key=fabric-wastage", icon: "\u{267B}\u{FE0F}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-quotations", label: "Quotations", href: "/accounts/quotations/", icon: "\u{1F4C4}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "accounts-payments", label: "Invoices", href: "/accounts/payments/", icon: "\u{1F9FE}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-party-ledger", label: "Party Ledger", href: "/reports/?key=party-ledger", icon: "\u{1F4D2}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "store-purchases", label: "Purchase Bills", href: "/store/purchases/", icon: "\u{1F4E5}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-supplier-ledger", label: "Supplier Ledger", href: "/reports/?key=supplier-ledger", icon: "\u{1F4D5}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-sales-pnl-cash", label: "Sales, P&L & Cash", href: "/reports/?key=sales-pnl-cash", icon: "\u{1F4B0}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "report-activity-log", label: "Activity Log", href: "/reports/?key=activity-log", icon: "\u{1F5C3}\u{FE0F}", roles: ["ADMIN"], adminNav: true, section: "Admin" },
  { key: "merch-dashboard", label: "Dashboard", href: "/dashboard/merchandising/", icon: "\u{1F4CA}", roles: ["ADMIN", "MERCHANDISE"], section: "Merchandising" },
  { key: "merch-orders", label: "Orders", href: "/merchandising/orders/", icon: "\u{1F4DD}", roles: ["ADMIN", "MERCHANDISE"], section: "Merchandising" },
  { key: "merch-parties", label: "Parties", href: "/merchandising/parties/", icon: "\u{1F9D1}\u{200D}\u{1F4BC}", roles: ["ADMIN", "MERCHANDISE"], section: "Merchandising" },
  { key: "merch-products", label: "Products", href: "/merchandising/products/", icon: "\u{1F455}", roles: ["ADMIN", "MERCHANDISE"], section: "Merchandising" },
  { key: "merch-colors", label: "Colors", href: "/merchandising/colors/", icon: "\u{1F3A8}", roles: ["ADMIN", "MERCHANDISE"], section: "Merchandising" },
  { key: "merch-fabric", label: "Fabric Types", href: "/merchandising/fabric-types/", icon: "\u{1F9F5}", roles: ["ADMIN", "MERCHANDISE"], section: "Merchandising" },
  { key: "store", label: "Store", href: "/dashboard/store/", icon: "\u{1F9F5}", roles: ["ADMIN", "STORE_MANAGER"], section: "Store" },
  { key: "store-purchases", label: "Purchase Orders", href: "/store/purchases/", icon: "\u{1F4E5}", roles: ["ADMIN", "STORE_MANAGER"], section: "Store" },
  { key: "store-purchase-order-specific", label: "Order-Specific Purchase", href: "/store/purchases/order-specific/", icon: "\u{1F3AF}", roles: ["ADMIN", "STORE_MANAGER"], section: "Store" },
  { key: "store-purchase-bulk", label: "Bulk Purchase", href: "/store/purchases/bulk/", icon: "\u{1F4E6}", roles: ["ADMIN", "STORE_MANAGER"], section: "Store" },
  { key: "store-purchase-customer-supplied", label: "Customer Supplied", href: "/store/purchases/customer-supplied/", icon: "\u{1F381}", roles: ["ADMIN", "STORE_MANAGER"], section: "Store" },
  { key: "store-accessories", label: "Accessories", href: "/store/accessories/", icon: "\u{1F9F7}", roles: ["ADMIN", "STORE_MANAGER"], section: "Store" },
  // Fabric-to-Cutting and Accessory-to-Operator issuing now live inside the
  // single Stock page (issue straight from a stock row) -- no separate pages.
  { key: "store-stock", label: "Stock", href: "/store/stock/", icon: "\u{1F4CB}", roles: ["ADMIN", "STORE_MANAGER"], section: "Store" },
  { key: "store-finished-goods", label: "Finished Goods", href: "/store/finished-goods/", icon: "\u{1F4E6}", roles: ["ADMIN", "STORE_MANAGER"], section: "Store" },
  { key: "store-vendors", label: "Vendors", href: "/store/vendors/", icon: "\u{1F91D}", roles: ["ADMIN", "STORE_MANAGER"], section: "Store" },
  { key: "cutting", label: "Cutting Dashboard", href: "/dashboard/cutting/", icon: "\u{2702}\u{FE0F}", roles: ["ADMIN", "CUTTING_SUPERVISOR"], section: "Cutting" },
  { key: "cutting-orders-list", label: "Cutting Orders", href: "/cutting/orders/", icon: "\u{1F4CB}", roles: ["ADMIN", "CUTTING_SUPERVISOR"], section: "Cutting" },
  { key: "production", label: "Production", href: "/dashboard/production/", icon: "\u{1F3ED}", roles: ["ADMIN", "PRODUCTION_SUPERVISOR"], section: "Production" },
  { key: "production-accessories", label: "Accessories Received", href: "/production/accessories/", icon: "\u{1F9F7}", roles: ["ADMIN", "PRODUCTION_SUPERVISOR"], section: "Production" },
  { key: "production-bundle-allocation", label: "Bundle Allocation", href: "/production/bundle-allocation/", icon: "\u{1F9D1}\u{200D}\u{1F3ED}", roles: ["ADMIN", "PRODUCTION_SUPERVISOR"], section: "Production" },
  { key: "production-send-to-finishing", label: "Send to Process", href: "/production/send-to-finishing/", icon: "\u{1F69A}", roles: ["ADMIN", "PRODUCTION_SUPERVISOR"], section: "Production" },
  { key: "production-processing", label: "Processing (Wash/Print/Embroidery)", href: "/production/processing/", icon: "\u{1F9FA}", roles: ["ADMIN", "PRODUCTION_SUPERVISOR"], section: "Production" },
  { key: "production-operators", label: "Operators", href: "/production/operators/", icon: "\u{1F465}", roles: ["ADMIN", "PRODUCTION_SUPERVISOR"], section: "Production" },
  { key: "production-performance", label: "Performance & Income", href: "/production/performance/", icon: "\u{1F4C8}", roles: ["ADMIN", "PRODUCTION_SUPERVISOR"], section: "Production" },
  { key: "finishing", label: "Finishing & Dispatch", href: "/dashboard/finishing/", icon: "\u{1F4E6}", roles: ["ADMIN", "FINISHING_SUPERVISOR"], section: "Finishing" },
  { key: "finishing-operations", label: "Quality Check", href: "/finishing/operations/", icon: "\u{2705}", roles: ["ADMIN", "FINISHING_SUPERVISOR"], section: "Finishing" },
  { key: "finishing-dispatch", label: "Dispatch", href: "/finishing/dispatch/", icon: "\u{1F69A}", roles: ["ADMIN", "FINISHING_SUPERVISOR"], section: "Finishing" },
  { key: "accounts-dashboard", label: "Dashboard", href: "/dashboard/accounts/", icon: "\u{1F4B0}", roles: ["ADMIN", "ACCOUNTS"], section: "Accounts" },
  { key: "report-quotations", label: "Quotations", href: "/accounts/quotations/", icon: "\u{1F4C4}", roles: ["ADMIN", "ACCOUNTS"], section: "Accounts" },
  { key: "accounts-payments", label: "Invoices", href: "/accounts/payments/", icon: "\u{1F9FE}", roles: ["ADMIN", "ACCOUNTS"], section: "Accounts" },
  { key: "report-party-ledger", label: "Party Ledger", href: "/reports/?key=party-ledger", icon: "\u{1F4D2}", roles: ["ADMIN", "ACCOUNTS"], section: "Accounts" },
  { key: "accounts-purchase-orders", label: "Purchase Bills", href: "/accounts/purchase-orders/", icon: "\u{1F4E5}", roles: ["ADMIN", "ACCOUNTS"], section: "Accounts" },
  { key: "report-supplier-ledger", label: "Supplier Ledger", href: "/reports/?key=supplier-ledger", icon: "\u{1F4D5}", roles: ["ADMIN", "ACCOUNTS"], section: "Accounts" },
  { key: "report-sales-pnl-cash", label: "Sales, P&L & Cash", href: "/reports/?key=sales-pnl-cash", icon: "\u{1F4B0}", roles: ["ADMIN", "ACCOUNTS"], section: "Accounts" },
  { key: "accounts-income-expenses", label: "Income & Expenses", href: "/accounts/income-expenses/", icon: "\u{1F4C8}", roles: ["ADMIN", "ACCOUNTS"], section: "Accounts" },
  { key: "accounts-order-pnl", label: "Order P&L", href: "/accounts/order-pnl/", icon: "\u{1F4CA}", roles: ["ADMIN", "ACCOUNTS"], section: "Accounts" },
  { key: "operator", label: "My Work", href: "/dashboard/operator/", icon: "\u{1F9D1}\u{200D}\u{1F3ED}", roles: ["ADMIN", "OPERATOR"], section: "Operator" },
];

const Auth = {
  getAccess() { return localStorage.getItem("gms_access"); },
  getRefresh() { return localStorage.getItem("gms_refresh"); },
  getRole() { return localStorage.getItem("gms_role"); },
  getFullName() { return localStorage.getItem("gms_full_name"); },
  setTokens({ access, refresh, role, full_name }) {
    localStorage.setItem("gms_access", access);
    if (refresh) localStorage.setItem("gms_refresh", refresh);
    if (role) localStorage.setItem("gms_role", role);
    if (full_name) localStorage.setItem("gms_full_name", full_name);
  },
  clear() {
    ["gms_access", "gms_refresh", "gms_role", "gms_full_name"].forEach(k => localStorage.removeItem(k));
  },
  isLoggedIn() { return !!this.getAccess(); },
  logout() {
    this.clear();
    window.location.href = "/";
  },
  /** Call at the top of every dashboard page.
   *  allowedRoles: roles permitted on this page (ADMIN is always allowed). */
  guardPage(allowedRoles) {
    if (!this.isLoggedIn()) { window.location.href = "/"; return false; }
    const role = this.getRole();
    if (role !== "ADMIN" && !allowedRoles.includes(role)) {
      window.location.href = ROLE_DASHBOARD[role] || "/";
      return false;
    }
    return true;
  },
};

async function login(email, password) {
  const res = await fetch(`${API_BASE}/auth/login/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error("Invalid email or password.");
  const data = await res.json();
  Auth.setTokens(data);
  return data;
}

function redirectToOwnDashboard() {
  const role = Auth.getRole();
  window.location.href = ROLE_DASHBOARD[role] || "/dashboard/admin/";
}

async function refreshToken() {
  const refresh = Auth.getRefresh();
  if (!refresh) return false;
  const res = await fetch(`${API_BASE}/auth/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  Auth.setTokens({ access: data.access });
  return true;
}

/** Authenticated fetch. Retries once after a silent token refresh on 401. */
async function apiFetch(path, options = {}) {
  const doFetch = () => fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${Auth.getAccess()}`,
      ...(options.headers || {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
  });

  let res = await doFetch();
  if (res.status === 401) {
    const refreshed = await refreshToken();
    if (refreshed) res = await doFetch();
    else { Auth.logout(); return; }
  }
  return res;
}

async function apiGet(path) {
  const res = await apiFetch(path);
  if (!res.ok) throw new Error(await extractError(res));
  return res.json();
}
async function apiPost(path, body) {
  const res = await apiFetch(path, { method: "POST", body });
  if (!res.ok) throw new Error(await extractError(res));
  return res.status === 204 ? {} : res.json();
}
async function apiPatch(path, body) {
  const res = await apiFetch(path, { method: "PATCH", body });
  if (!res.ok) throw new Error(await extractError(res));
  return res.json();
}
async function apiDelete(path) {
  const res = await apiFetch(path, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(await extractError(res));
  return true;
}
async function extractError(res) {
  try {
    const data = await res.json();
    return typeof data === "string" ? data : JSON.stringify(data);
  } catch { return `Request failed (${res.status})`; }
}

/** Fetches a list endpoint and returns every row, walking pagination
 *  instead of trusting page 1 (crud.js's loadOptions() truncates at
 *  PAGE_SIZE=20 -- pages that cache master data client-side must not). */
async function fetchAll(path) {
  let out = [], next = path;
  while (next) {
    const data = await apiGet(next);
    if (Array.isArray(data)) { out = out.concat(data); break; }
    out = out.concat(data.results || []);
    next = data.next ? new URL(data.next).pathname.replace(/^\/api/, "") + new URL(data.next).search : null;
  }
  return out;
}

/* ---- small DOM helpers ---- */
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  });
  (Array.isArray(children) ? children : [children]).forEach(c => {
    if (c === null || c === undefined) return;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return node;
}

function badge(text) {
  return el("span", { class: `badge ${String(text).toLowerCase()}` }, String(text));
}

/* ---- small form-building helpers shared by pages with dynamic/repeatable
   rows (Order Builder, Store's purchase builders) ---- */
function selectEl(attrs, options, selectedValue, placeholder) {
  const select = el("select", attrs);
  if (placeholder) select.appendChild(el("option", { value: "" }, placeholder));
  options.forEach(o => select.appendChild(el("option", { value: String(o.value) }, o.label)));
  select.value = selectedValue === null || selectedValue === undefined ? "" : String(selectedValue);
  return select;
}
function multiSelectEl(attrs, options, selectedValues) {
  const select = el("select", { ...attrs, multiple: "multiple" });
  const selected = new Set((selectedValues || []).map(String));
  options.forEach(o => {
    const opt = el("option", { value: String(o.value) }, o.label);
    if (selected.has(String(o.value))) opt.selected = true;
    select.appendChild(opt);
  });
  return select;
}
function numberInput(value, onInput, extra = {}) {
  return el("input", { type: "number", value: value ?? "", oninput: e => onInput(e.target.value), ...extra });
}
function field(label, inputEl) {
  return el("div", { class: "form-row" }, [el("label", {}, label), inputEl]);
}
function removeIconBtn(title, disabled, onclick) {
  return el("button", { class: "icon-btn remove-icon", type: "button", title, ...(disabled ? { disabled: "disabled" } : {}), onclick }, "✕");
}
function colorDot(hex) {
  return el("span", { class: "color-dot", style: `background:${hex || "#e5e9f0"};` });
}

function fmtMoney(n) {
  return "Rs. " + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/* ============================================================
   Date entry policy (applied to every date input, anywhere):
     • empty date fields default to TODAY (so the current date shows),
     • operational dates cannot be in the PAST (min = today).
   Financial/period dates are historical by nature — mark those inputs
   with class "allow-past" (or field option allowPast in crud.js) to skip
   the no-past rule; they still default to today.
   ============================================================ */
/* ---- Dark / light theme: persisted, applied early (see base.html head),
   toggled from the topbar button. ---- */
(function initTheme() {
  function apply(t) {
    document.documentElement.setAttribute("data-theme", t);
    const b = document.getElementById("theme-toggle");
    if (b) b.textContent = t === "dark" ? "☀️" : "🌙";
  }
  function current() { try { return localStorage.getItem("gms_theme") || "light"; } catch (e) { return "light"; } }
  function wire() {
    apply(current());
    const b = document.getElementById("theme-toggle");
    if (b && !b.dataset.wired) {
      b.dataset.wired = "1";
      b.addEventListener("click", () => {
        const t = current() === "dark" ? "light" : "dark";
        try { localStorage.setItem("gms_theme", t); } catch (e) {}
        apply(t);
      });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire);
  else wire();
})();

function todayISO() { return new Date().toISOString().slice(0, 10); }
function applyDateConstraints(root) {
  const scope = (root && root.querySelectorAll) ? root : document;
  scope.querySelectorAll('input[type="date"]:not([data-dc])').forEach(inp => {
    inp.setAttribute("data-dc", "1");
    if (!inp.value) inp.value = todayISO();
    if (!inp.classList.contains("allow-past") && !inp.min) inp.min = todayISO();
  });
}
(function initDateConstraints() {
  if (typeof MutationObserver === "undefined") return;
  const obs = new MutationObserver(() => applyDateConstraints(document));
  const start = () => { applyDateConstraints(document); obs.observe(document.body, { childList: true, subtree: true }); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

/* ============================================================
   UI feedback toolkit — toasts + confirm/alert dialogs.
   Non-blocking, styled, and available on every page (api.js
   loads before crud.js and all page scripts).
   ============================================================ */

/** Slide-in toast. type: success | error | warning | info. Returns a
 *  dismiss() fn. Auto-dismisses (errors linger a little longer). */
function toast(message, type = "info", opts = {}) {
  let host = document.getElementById("toast-host");
  if (!host) { host = el("div", { id: "toast-host", class: "toast-host" }); document.body.appendChild(host); }
  const icons = { success: "✓", error: "✕", warning: "⚠", info: "ℹ" };
  let timer;
  const remove = () => { clearTimeout(timer); node.classList.add("toast-out"); setTimeout(() => node.remove(), 220); };
  const node = el("div", { class: `toast toast-${type}`, role: "status" }, [
    el("span", { class: "toast-icon" }, icons[type] || icons.info),
    el("div", { class: "toast-body" }, String(message)),
    el("button", { class: "toast-close", type: "button", "aria-label": "Dismiss", onclick: remove }, "×"),
  ]);
  host.appendChild(node);
  const duration = opts.duration ?? (type === "error" ? 6500 : 3600);
  timer = setTimeout(remove, duration);
  return remove;
}

/** Convenience wrappers so pages can write notify.success("Saved"). */
const notify = {
  success: (m) => toast(m, "success"),
  error: (m) => toast(m, "error"),
  warning: (m) => toast(m, "warning"),
  info: (m) => toast(m, "info"),
};

/** Base modal dialog used by showConfirm/showAlert. Self-contained so it
 *  does not depend on crud.js's modal. Resolves when the user responds. */
function showDialog(opts) {
  const {
    title = "", message = "", icon, tone = "brand",
    confirmText = "Confirm", cancelText = "Cancel", showCancel = true, resolve,
  } = opts;
  const overlay = el("div", { class: "modal-overlay dialog-overlay" });
  const done = (val) => { document.removeEventListener("keydown", onKey); overlay.classList.add("dialog-out"); setTimeout(() => overlay.remove(), 160); resolve(val); };
  const onKey = (e) => { if (e.key === "Escape") done(false); if (e.key === "Enter") done(true); };
  overlay.addEventListener("click", (e) => { if (e.target === overlay) done(false); });
  document.addEventListener("keydown", onKey);

  const defaultIcon = { danger: "⚠", success: "✓", warning: "⚠", brand: "?" }[tone] || "?";
  const confirmBtn = el("button", { class: tone === "danger" ? "danger" : (tone === "success" ? "success" : ""), type: "button", onclick: () => done(true) }, confirmText);
  const card = el("div", { class: "modal-card dialog-card" }, [
    el("div", { class: `dialog-icon dialog-${tone}` }, icon || defaultIcon),
    title ? el("h3", { class: "dialog-title" }, title) : null,
    el("p", { class: "dialog-message" }, message),
    el("div", { class: "dialog-actions" }, [
      showCancel ? el("button", { class: "secondary", type: "button", onclick: () => done(false) }, cancelText) : null,
      confirmBtn,
    ]),
  ]);
  overlay.appendChild(card);
  document.body.appendChild(overlay);
  confirmBtn.focus();
}

/** Promise<boolean> confirm dialog. Usage: if (await showConfirm("...")) {...}
 *  opts: { title, tone:'danger', confirmText, cancelText, icon } */
function showConfirm(message, opts = {}) {
  return new Promise((resolve) => showDialog({ message, resolve, ...opts }));
}

/** Promise<void> acknowledgement dialog (single OK button). */
function showAlert(message, opts = {}) {
  return new Promise((resolve) => showDialog({ message, resolve, showCancel: false, confirmText: opts.confirmText || "OK", ...opts }));
}

/** Promise<string|null> input dialog — a styled replacement for prompt().
 *  opts: { title, message, label, placeholder, value, required, multiline,
 *          number, min, max, confirmText, tone }. Resolves the entered string
 *  (trimmed) or null on cancel. */
function showPrompt(opts = {}) {
  const { title = "", message = "", label = "", placeholder = "", value = "",
          required = false, multiline = false, number = false, min, max,
          confirmText = "Save", tone = "brand" } = opts;
  return new Promise((resolve) => {
    const overlay = el("div", { class: "modal-overlay dialog-overlay" });
    const input = multiline
      ? el("textarea", { class: "dialog-input", rows: "3", placeholder }, value != null ? String(value) : "")
      : el("input", { class: "dialog-input", type: number ? "number" : "text", placeholder, value: value != null ? String(value) : "",
          ...(min != null ? { min: String(min) } : {}), ...(max != null ? { max: String(max) } : {}) });
    const err = el("div", { class: "error-msg", style: "display:none;margin-top:0.4rem;" });
    const done = (val) => { document.removeEventListener("keydown", onKey); overlay.classList.add("dialog-out"); setTimeout(() => overlay.remove(), 160); resolve(val); };
    const submit = () => {
      const v = String(input.value).trim();
      if (required && !v) { err.textContent = "This field is required."; err.style.display = "block"; return; }
      if (number && v !== "") {
        const n = Number(v);
        if (Number.isNaN(n) || (min != null && n < Number(min)) || (max != null && n > Number(max))) {
          err.textContent = `Enter a number${min != null ? ` between ${min}` : ""}${max != null ? ` and ${max}` : ""}.`; err.style.display = "block"; return;
        }
      }
      done(v);
    };
    const onKey = (e) => { if (e.key === "Escape") done(null); if (e.key === "Enter" && !multiline) submit(); };
    overlay.addEventListener("click", (e) => { if (e.target === overlay) done(null); });
    document.addEventListener("keydown", onKey);
    const card = el("div", { class: "modal-card dialog-card", style: "text-align:left;" }, [
      title ? el("h3", { class: "dialog-title", style: "text-align:left;" }, title) : null,
      message ? el("p", { class: "dialog-message", style: "text-align:left;" }, message) : null,
      label ? el("label", { class: "dialog-label" }, label) : null,
      input, err,
      el("div", { class: "dialog-actions" }, [
        el("button", { class: "secondary", type: "button", onclick: () => done(null) }, "Cancel"),
        el("button", { class: tone === "danger" ? "danger" : "", type: "button", onclick: submit }, confirmText),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    setTimeout(() => input.focus(), 30);
  });
}

/* Upgrade every legacy alert() call (there are ~30 across the pages) into a
   styled toast — no per-page edits needed. Message text decides the tone. */
(function upgradeNativeAlert() {
  window.__nativeAlert = window.alert.bind(window);
  window.alert = function (msg) {
    const s = String(msg).replace(/^Error:\s*/i, "");
    let type = "info";
    if (/error|could not|couldn't|failed|exception|unavailable/i.test(msg)) type = "error";
    else if (/select|choose|fill|enter|require|valid|reason|must|please/i.test(msg)) type = "warning";
    toast(s, type);
  };
})();

/** Reusable data table with client-side search, sortable columns (arrow
 *  indicators) and pagination. Renders into `container` (cleared each call).
 *  columns: [{ label, key?, render?(row)->node|string, value?(row) (sort/search key),
 *              sortable? (default true when a key/value exists) }]
 *  Returns { setRows(rows) } to refresh data in place. */
function dataTable(container, opts) {
  const columns = opts.columns;
  const pageSize = opts.pageSize || 10;
  const st = { search: "", sortKey: opts.initialSort ? opts.initialSort.key : null,
               sortDir: (opts.initialSort && opts.initialSort.dir) || "asc", page: 1 };
  const keyOf = (col, i) => col.key || col.label || String(i);
  const rawValue = (col, row) => col.value ? col.value(row) : (col.key ? row[col.key] : null);
  const canSort = (col) => col.sortable !== false && (col.key || col.value);

  function processed() {
    let rows = (opts.rows || []).slice();
    if (st.search) {
      const q = st.search.toLowerCase();
      rows = rows.filter(row => columns.some(c => {
        const v = rawValue(c, row);
        return v != null && String(v).toLowerCase().includes(q);
      }));
    }
    if (st.sortKey != null) {
      const col = columns.find((c, i) => keyOf(c, i) === st.sortKey);
      if (col) rows.sort((a, b) => {
        let av = rawValue(col, a), bv = rawValue(col, b);
        av = av == null ? "" : av; bv = bv == null ? "" : bv;
        const an = Number(av), bn = Number(bv);
        const cmp = (!isNaN(an) && !isNaN(bn) && av !== "" && bv !== "")
          ? an - bn : String(av).localeCompare(String(bv), undefined, { numeric: true });
        return st.sortDir === "asc" ? cmp : -cmp;
      });
    }
    return rows;
  }

  function render() {
    container.innerHTML = "";
    const all = processed();
    const totalPages = Math.max(1, Math.ceil(all.length / pageSize));
    if (st.page > totalPages) st.page = totalPages;
    const pageRows = all.slice((st.page - 1) * pageSize, (st.page - 1) * pageSize + pageSize);

    if (opts.searchable !== false) {
      container.appendChild(el("div", { class: "table-toolbar" }, [
        el("input", { type: "search", class: "table-search", placeholder: opts.searchPlaceholder || "Search…", value: st.search,
          oninput: e => { st.search = e.target.value; st.page = 1; render(); } }),
        el("span", { class: "table-count" }, `${all.length} record${all.length === 1 ? "" : "s"}`),
      ]));
    }

    const table = el("table", { class: "data-table" });
    table.appendChild(el("thead", {}, el("tr", {}, columns.map((col, i) => {
      const k = keyOf(col, i);
      const sortable = canSort(col);
      const sorted = st.sortKey === k;
      const attrs = {};
      if (sortable) {
        attrs.class = "sortable" + (sorted ? " sorted" : "");
        attrs.onclick = () => {
          if (st.sortKey === k) st.sortDir = st.sortDir === "asc" ? "desc" : "asc";
          else { st.sortKey = k; st.sortDir = "asc"; }
          render();
        };
      }
      const arrow = sorted ? (st.sortDir === "asc" ? "▲" : "▼") : (sortable ? "⇅" : "");
      return el("th", attrs, [col.label + " ", el("span", { class: "sort-arrow" }, arrow)]);
    }))));
    const tbody = el("tbody");
    pageRows.forEach(row => tbody.appendChild(el("tr", {}, columns.map(col => {
      const v = col.render ? col.render(row) : rawValue(col, row);
      return el("td", {}, v instanceof HTMLElement ? v : String(v ?? ""));
    }))));
    table.appendChild(tbody);
    container.appendChild(el("div", { style: "overflow-x:auto;" }, table));

    if (!all.length) container.appendChild(el("p", { class: "muted", style: "margin-top:0.6rem;" }, opts.emptyText || "No records."));

    if (totalPages > 1) {
      const prevAttrs = { class: "secondary", type: "button", onclick: () => { if (st.page > 1) { st.page--; render(); } } };
      const nextAttrs = { class: "secondary", type: "button", onclick: () => { if (st.page < totalPages) { st.page++; render(); } } };
      if (st.page <= 1) prevAttrs.disabled = "disabled";
      if (st.page >= totalPages) nextAttrs.disabled = "disabled";
      container.appendChild(el("div", { class: "table-pager" }, [
        el("button", prevAttrs, "‹ Prev"),
        el("span", { class: "muted" }, `Page ${st.page} of ${totalPages}`),
        el("button", nextAttrs, "Next ›"),
      ]));
    }
  }

  render();
  return { setRows(rows) { opts.rows = rows; st.page = 1; render(); } };
}

/** Change-password modal (self-service, any logged-in user). */
function openChangePasswordModal() {
  const oldI = el("input", { type: "password", autocomplete: "current-password" });
  const newI = el("input", { type: "password", autocomplete: "new-password" });
  const confI = el("input", { type: "password", autocomplete: "new-password" });
  const errorBox = el("div", { class: "error-msg", style: "display:none;" });
  const submit = async () => {
    errorBox.style.display = "none";
    if (!oldI.value || !newI.value) { errorBox.textContent = "Enter your current and new password."; errorBox.style.display = "block"; return; }
    if (newI.value.length < 8) { errorBox.textContent = "New password must be at least 8 characters."; errorBox.style.display = "block"; return; }
    if (newI.value !== confI.value) { errorBox.textContent = "New passwords do not match."; errorBox.style.display = "block"; return; }
    try {
      await apiPost("/users/change_password/", { old_password: oldI.value, new_password: newI.value });
      closeCrudModal();
      toast("Password updated successfully.", "success");
    } catch (e) { errorBox.textContent = e.message; errorBox.style.display = "block"; }
  };
  showCrudModal("Change Password", [
    errorBox, field("Current Password", oldI), field("New Password", newI), field("Confirm New Password", confI),
  ], [
    el("button", { type: "button", onclick: submit }, "Update Password"),
    el("button", { class: "secondary", type: "button", onclick: closeCrudModal }, "Cancel"),
  ]);
  oldI.focus();
}

/** Builds the sidebar + topbar chrome. activeKey matches a MENU[].key. */
function renderShell(activeKey, pageTitle) {
  const role = Auth.getRole();
  const sidebar = document.getElementById("sidebar-nav");
  const topbarTitle = document.getElementById("topbar-title");
  const userInfo = document.getElementById("user-info");

  if (topbarTitle) topbarTitle.textContent = pageTitle || "";

  if (sidebar) {
    let lastSection = null;
    // Admin gets its own curated 23-item sidebar (adminNav); every other role
    // sees only the items for their department.
    MENU.filter(item => role === "ADMIN" ? item.adminNav === true : item.roles.includes(role)).forEach(item => {
      if (item.section && item.section !== lastSection) {
        sidebar.appendChild(el("div", { class: "nav-section" }, item.section));
        lastSection = item.section;
      }
      const a = el("a", { href: item.href, class: item.key === activeKey ? "active" : "" }, [
        el("span", { class: "menu-icon" }, item.icon),
        el("span", { class: "nav-text" }, item.label),
      ]);
      sidebar.appendChild(a);
    });
  }

  if (userInfo) {
    const fullName = Auth.getFullName() || "";
    const menu = el("div", { class: "user-menu", style: "display:none;" }, [
      el("button", { class: "user-menu-item", type: "button", onclick: () => { closeUserMenu(); openChangePasswordModal(); } }, [el("span", {}, "🔑"), "Change Password"]),
      el("button", { class: "user-menu-item danger-item", type: "button", onclick: () => Auth.logout() }, [el("span", {}, "↩"), "Logout"]),
    ]);
    const chip = el("button", { class: "user-chip", type: "button", "aria-haspopup": "true" }, [
      el("div", { class: "user-avatar" }, initialsOf(fullName, role)),
      el("div", { class: "user-meta" }, [
        el("div", { class: "user-name" }, fullName),
        el("div", { class: "user-role" }, ROLE_LABELS[role] || role || ""),
      ]),
      el("span", { class: "user-caret" }, "▾"),
    ]);
    const wrap = el("div", { class: "user-menu-wrap" }, [chip, menu]);
    function closeUserMenu() { menu.style.display = "none"; }
    chip.addEventListener("click", (e) => { e.stopPropagation(); menu.style.display = menu.style.display === "none" ? "block" : "none"; });
    document.addEventListener("click", (e) => { if (!wrap.contains(e.target)) closeUserMenu(); });
    userInfo.appendChild(wrap);
  }

  wireSidebarToggle();
  renderNotificationBell();
}

/** Two-letter avatar initials from a full name (falls back to the role). */
function initialsOf(fullName, role) {
  const parts = (fullName || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (role || "U").slice(0, 2).toUpperCase();
}

/** Off-canvas sidebar drawer for narrow screens (hamburger + backdrop). */
function wireSidebarToggle() {
  const shell = document.getElementById("app-shell");
  const toggle = document.getElementById("sidebar-toggle");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (!shell || !toggle) return;
  const close = () => shell.classList.remove("nav-open");
  toggle.addEventListener("click", () => shell.classList.toggle("nav-open"));
  backdrop?.addEventListener("click", close);
  document.querySelectorAll("#sidebar-nav a").forEach(a => a.addEventListener("click", close));
}

/** Bell icon + unread-count badge in the shared topbar, with a click-to-open
 *  dropdown of recent notifications -- created at department handoff points
 *  (bundle sent to Production, a shortage pending review, etc). */
async function renderNotificationBell() {
  const wrap = document.getElementById("notification-bell");
  if (!wrap) return;
  wrap.innerHTML = "";

  const btn = el("button", { class: "bell-btn", type: "button" }, "🔔");
  const badge = el("span", { class: "bell-badge", style: "display:none;" }, "0");
  const dropdown = el("div", { class: "bell-dropdown", style: "display:none;" });
  wrap.appendChild(el("div", { class: "bell-wrap" }, [btn, badge, dropdown]));

  async function refresh() {
    try {
      const unread = await fetchAll("/users/notifications/my/?is_read=false");
      if (unread.length) { badge.textContent = String(unread.length); badge.style.display = ""; }
      else { badge.style.display = "none"; }
    } catch (e) { /* not fatal -- bell just stays quiet */ }
  }

  async function openDropdown() {
    dropdown.innerHTML = "Loading...";
    dropdown.style.display = "block";
    try {
      const items = await fetchAll("/users/notifications/my/");
      dropdown.innerHTML = "";
      if (!items.length) {
        dropdown.appendChild(el("div", { class: "bell-empty" }, "No notifications yet."));
      } else {
        dropdown.appendChild(el("button", { class: "secondary bell-markall", type: "button", onclick: async () => {
          await apiPost("/users/notifications/mark_all_read/", {});
          await refresh(); await openDropdown();
        } }, "Mark all read"));
        items.slice(0, 20).forEach(n => {
          const row = el("div", { class: `bell-item${n.is_read ? "" : " unread"}` }, [
            el("div", {}, n.message),
            el("div", { class: "bell-time" }, n.created_at ? n.created_at.slice(0, 16).replace("T", " ") : ""),
          ]);
          row.addEventListener("click", async () => {
            if (!n.is_read) await apiPost(`/users/notifications/${n.id}/mark_read/`, {});
            if (n.link) window.location.href = n.link;
          });
          dropdown.appendChild(row);
        });
      }
    } catch (e) { dropdown.innerHTML = "Could not load notifications."; }
  }

  btn.addEventListener("click", () => {
    if (dropdown.style.display === "block") { dropdown.style.display = "none"; return; }
    openDropdown();
  });
  document.addEventListener("click", e => { if (!wrap.contains(e.target)) dropdown.style.display = "none"; });

  await refresh();
}

/** Lightweight custom trend visualization -- a row of flexbox bars sized by
 *  % of the row's max value. No charting library added (this project loads
 *  nothing from a CDN); good enough for "last N weeks" style summaries. */
function renderTrendBars(rows, labelKey, valueKey, opts = {}) {
  if (!rows.length) return el("p", { class: "muted" }, "Not enough data yet for a trend.");
  const max = Math.max(...rows.map(r => Number(r[valueKey]) || 0), 1);
  const bars = rows.map(r => {
    const value = Number(r[valueKey]) || 0;
    const pct = Math.round((value / max) * 100);
    return el("div", { class: "trend-col" }, [
      el("div", { class: "trend-bar-track" }, [el("div", { class: "trend-bar-fill", style: `height:${pct}%;` })]),
      el("div", { class: "trend-value" }, String(value)),
      el("div", { class: "trend-label" }, String(r[labelKey] ?? "").slice(0, 10)),
    ]);
  });
  return el("div", { class: "trend-bars" }, bars);
}

/** Label/value row for read-only detail views -- full width, for longer
 *  free-text values (addresses, remarks). */
function detailRow(label, value) {
  return el("div", { class: "form-row" }, [el("label", {}, label), el("div", {}, value)]);
}

/** Compact label/value cell for the 2-column detail grid. */
function detailItem(label, value) {
  return el("div", { class: "detail-item" }, [
    el("div", { class: "detail-label" }, label),
    el("div", { class: "detail-value" }, value),
  ]);
}
/** 2-column grid of [label, value] pairs -- the standard "profile" layout
 *  for View modals (party info, order/PO header facts). */
function detailGrid(pairs) {
  return el("div", { class: "detail-grid" }, pairs.map(([label, value]) => detailItem(label, value)));
}

/** Read-only breakdown of one order: items -> colors -> size/ratio rows.
 *  Shared by the Parties page's order-history view and the Orders page's
 *  "View" action, so the nesting only has to be described once. */
function renderOrderSummary(order) {
  const isFixed = order.order_type === "FIXED_QUANTITY";
  const totalQty = isFixed
    ? order.items.reduce((s, it) => s + it.colors.reduce((s2, c) => s2 + c.size_lines.reduce((s3, l) => s3 + (Number(l.quantity) || 0), 0), 0), 0)
    : null;

  const itemBlocks = order.items.map(item => {
    const colorLines = item.colors.map(color => {
      const sizesText = color.size_lines.map(l =>
        `${l.size_name}: ${isFixed ? `${l.quantity} pcs` : `ratio ${l.ratio_part}`}`
      ).join(", ");
      return el("div", { class: "detail-row-line" }, [colorDot(color.color_hex), el("span", {}, `${color.color_name} — ${sizesText || "no sizes"}`)]);
    });
    return el("div", { class: "subcard level-color" }, [
      el("div", { class: "subcard-header" }, [el("span", { class: "subcard-title" }, `${item.product_code} — ${item.product_name}`)]),
      el("div", { class: "muted", style: "margin-bottom:0.3rem;" },
        `${item.fabric_type_name} · Operator rate: ${item.price_per_piece != null ? fmtMoney(item.price_per_piece) + "/pc" : "—"} · Inner: ${item.inner_required ? "Yes" : "No"} · Fusing: ${item.fusing_required ? "Yes" : "No"} · Resting: ${item.resting_needed ? "Yes" : "No"}`),
      ...colorLines,
    ]);
  });

  return el("div", {}, [
    el("div", { class: "summary-header" }, [
      el("div", { class: "summary-header-top" }, [el("span", { class: "summary-title" }, order.order_number), badge(order.status)]),
      el("div", { class: "muted" },
        `${isFixed ? "📦 Fixed Quantity" : "✂️ Ratio Based"} · ${order.order_date}${isFixed ? ` · Total: ${totalQty} pcs` : ""}`),
    ]),
    ...itemBlocks,
  ]);
}

/** Read-only breakdown of one purchase order: items with material
 *  (fabric type+color or accessory), ordered/received quantity, and rate
 *  once received. Shared by Store's Purchase Orders overview and the
 *  Accounts Purchase Orders panel's View action. */
function renderPOSummary(po) {
  const itemBlocks = po.items.map(item => {
    const icon = item.material_type === "FABRIC" ? "🧵" : "🧷";
    const material = item.material_type === "FABRIC"
      ? `${item.fabric_type_name || "?"} / ${item.color_name || "?"}`
      : (item.accessory_label || "?");
    const ordered = Number(item.quantity), received = Number(item.received_quantity);
    const remaining = ordered - received;
    const progress = ordered > 0 ? Math.round((received / ordered) * 100) : 0;
    const rateText = item.rate !== null && item.rate !== undefined ? `${fmtMoney(item.rate)} / unit` : "rate not set yet";
    return el("div", { class: "subcard level-color" }, [
      el("div", { class: "subcard-header" }, [
        el("span", { class: "subcard-title" }, `${icon} ${material}`),
        el("span", { class: "muted" }, `${progress}% received`),
      ]),
      el("div", {}, `Ordered ${item.quantity} ${item.unit || ""} · Received ${item.received_quantity}` +
        (remaining > 0 ? ` (${remaining} remaining)` : "") + ` · ${rateText}`),
    ]);
  });

  return el("div", {}, [
    el("div", { class: "summary-header" }, [
      el("div", { class: "summary-header-top" }, [el("span", { class: "summary-title" }, po.po_number), badge(po.receipt_status)]),
      el("div", { class: "muted" },
        `${po.po_type.replace(/_/g, " ")} · ${po.vendor_name || po.party_name || "—"}${po.order_number ? " · Order " + po.order_number : ""} · ${po.po_date}`),
    ]),
    ...itemBlocks,
  ]);
}

/** Admin/supervisor "operator profile" modal: personal details, lifetime
 *  production & efficiency, and a day-by-day breakdown of completed pieces
 *  and the money they earned (paid at the order's price_per_piece). Opened
 *  by clicking an operator's name. */
async function showOperatorReport(operatorId, operatorName) {
  const closeBtn = () => el("button", { class: "secondary", type: "button", onclick: closeCrudModal }, "Close");
  showCrudModal(`Operator — ${operatorName || ""}`,
    [el("p", { class: "muted" }, "Loading operator overview…")], [closeBtn()], { wide: true });

  let r;
  try { r = await apiGet(`/operators/operators/${operatorId}/report/`); }
  catch (e) { closeCrudModal(); toast("Could not load operator overview: " + e.message, "error"); return; }

  const o = r.operator, p = r.production, e = r.earnings;
  const pct = v => (v === null || v === undefined) ? "—" : `${v}%`;
  const tile = (label, value, kind) => el("div", { class: `op-kpi ${kind ? "op-" + kind : ""}` }, [
    el("div", { class: "op-kpi-value" }, String(value)),
    el("div", { class: "op-kpi-label" }, label),
  ]);

  const personal = detailGrid([
    ["Operator Type", o.operator_type === "GROUP" ? "Group" : "Individual"],
    ["Skill Level", o.skill_level || "—"],
    ["Contact", o.contact || "—"],
    ["Email", o.email || "—"],
    ["Joined Date", o.joined_date || "—"],
    ["Login Account", o.user_account ? "Linked" : "Not linked"],
    ["Address", o.address || "—"],
    ["Status", o.is_active ? "Active" : "Inactive"],
  ]);

  const kpis = el("div", { class: "op-kpi-grid" }, [
    tile("Bundles Received", p.bundles_received),
    tile("Completed Bundles", p.completed_bundles),
    tile("Pieces Completed", (p.pieces_completed || 0).toLocaleString(), "good"),
    tile("Pieces Lost", p.pieces_lost || 0, p.pieces_lost ? "bad" : ""),
    tile("Defects", p.total_defects || 0, p.total_defects ? "warn" : ""),
    tile("Efficiency", pct(p.efficiency_pct)),
    tile("Quality Rate", pct(p.quality_rate_pct)),
    tile("QC Pass Rate", pct(p.quality_pass_rate)),
    tile("Total Earned", fmtMoney(e.total_earned), "good"),
    tile("Pending Pay", fmtMoney(e.pending_amount), e.pending_amount ? "warn" : ""),
  ]);

  let dailyNode;
  if (!r.daily || !r.daily.length) {
    dailyNode = el("p", { class: "muted" }, "No completed work recorded yet.");
  } else {
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {}, ["Date", "Bundles", "Pieces Completed", "Amount Earned"].map(h => el("th", {}, h)))));
    const tb = el("tbody");
    r.daily.slice().reverse().forEach(d => {
      tb.appendChild(el("tr", {}, [
        el("td", {}, d.date),
        el("td", {}, String(d.bundles)),
        el("td", {}, Number(d.pieces).toLocaleString()),
        el("td", {}, fmtMoney(d.amount)),
      ]));
    });
    table.appendChild(tb);
    dailyNode = el("div", { style: "overflow-x:auto;" }, table);
  }

  // By-order summary: each order this operator worked on -> total bundles,
  // pieces received in those bundles, and pieces returned.
  const rows = r.assignments || [];
  let byOrderNode;
  if (!rows.length) {
    byOrderNode = el("p", { class: "muted" }, "No orders worked on yet.");
  } else {
    const map = new Map();
    rows.forEach(a => {
      const key = a.order_number || "—";
      const g = map.get(key) || { order: key, product: a.product || "—", bundles: 0, received: 0, returned: 0, lost: 0, defects: 0, earned: 0 };
      g.bundles += 1; g.received += Number(a.received || 0); g.returned += Number(a.returned || 0);
      g.lost += Number(a.lost || 0); g.defects += Number(a.defects || 0); g.earned += Number(a.earned || 0);
      map.set(key, g);
    });
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {}, ["Order", "Product", "Bundles", "Pieces Received", "Pieces Returned", "Lost", "Earned"].map(h => el("th", {}, h)))));
    const tb = el("tbody");
    [...map.values()].forEach(g => tb.appendChild(el("tr", {}, [
      el("td", {}, g.order), el("td", {}, g.product), el("td", {}, String(g.bundles)),
      el("td", {}, String(g.received)), el("td", {}, String(g.returned)),
      el("td", {}, g.lost ? el("span", { style: "color:var(--danger);font-weight:600;" }, String(g.lost)) : "0"),
      el("td", {}, fmtMoney(g.earned)),
    ])));
    table.appendChild(tb);
    byOrderNode = el("div", { style: "overflow-x:auto;" }, table);
  }

  // Per-bundle history: received / returned / lost / defects / earned.
  let bundleNode;
  if (!rows.length) {
    bundleNode = el("p", { class: "muted" }, "No bundles assigned yet.");
  } else {
    const table = el("table");
    table.appendChild(el("thead", {}, el("tr", {},
      ["Bundle", "Order / Item", "Received", "Returned", "Lost", "Defects", "Status", "Earned"].map(h => el("th", {}, h)))));
    const tb = el("tbody");
    rows.forEach(a => {
      const itemLabel = `${a.order_number}${a.product && a.product !== "—" ? " · " + a.product : ""}` +
        (a.color || a.size ? ` (${[a.color, a.size].filter(Boolean).join(" / ")})` : "");
      tb.appendChild(el("tr", {}, [
        el("td", {}, a.bundle_number),
        el("td", {}, itemLabel),
        el("td", {}, String(a.received ?? "—")),
        el("td", {}, a.returned === null || a.returned === undefined ? "—" : String(a.returned)),
        el("td", {}, a.lost ? el("span", { style: "color:var(--danger);font-weight:600;" }, String(a.lost)) : "0"),
        el("td", {}, a.defects ? el("span", { style: "color:#b98600;font-weight:600;" }, String(a.defects)) : "0"),
        el("td", {}, badge(a.status)),
        el("td", {}, fmtMoney(a.earned)),
      ]));
    });
    table.appendChild(tb);
    bundleNode = el("div", { style: "overflow-x:auto;" }, table);
  }

  const content = el("div", {}, [
    el("div", { class: "summary-header" }, [
      el("div", { class: "summary-header-top" }, [
        el("span", { class: "summary-title" }, o.name),
        badge(o.is_active ? "Active" : "Inactive"),
      ]),
      el("div", { class: "muted" }, `${o.operator_type === "GROUP" ? "Group" : "Individual"} operator · ${o.skill_level || "skill n/a"}`),
    ]),
    el("div", { class: "section-title", style: "margin-top:0.3rem;" }, "Personal details"),
    personal,
    el("div", { class: "section-title" }, "Performance overview"),
    kpis,
    el("div", { class: "section-title" }, "By order — bundles, pieces received & returned"),
    byOrderNode,
    el("div", { class: "section-title" }, "Bundle-by-bundle history"),
    bundleNode,
    el("div", { class: "section-title" }, "Daily completed pieces & earnings"),
    dailyNode,
  ]);

  showCrudModal(`Operator — ${o.name}`, [content], [closeBtn()], { wide: true });
}
