import { useState, useEffect, useCallback, useRef, createContext, useContext } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  Link,
  useNavigate,
  useParams,
  NavLink,
  useLocation,
} from "react-router-dom";
import Landing from "./Landing.jsx";

const API_BASE = "/api";
const jsonHeaders = { "Content-Type": "application/json" };

// Accepts either a fetch() promise or an already-resolved Response, so both
// `parseResponse(fetch(...))` and `parseResponse(await fetch(...))` work.
async function parseResponse(res, json = true) {
  const response = await res;
  if (!response || typeof response.json !== "function") {
    throw new Error("Unexpected response from the API");
  }

  let body = null;
  if (json) {
    body = await response.json().catch(() => null);
  }

  if (!response.ok) {
    throw new Error(
      detailOf(body) || `Request failed (${response.status})`
    );
  }
  return body;
}

// FastAPI reports validation errors as a list of {loc, msg} objects; collapse
// them into one readable line instead of leaking "[object Object]".
function detailOf(body) {
  const detail = body?.detail ?? body?.message;
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === "string") return d;
        const field = Array.isArray(d?.loc) ? d.loc.filter((p) => p !== "body").join(".") : "";
        return field ? `${field}: ${d?.msg || "invalid"}` : d?.msg || "invalid request";
      })
      .join("; ");
  }
  return JSON.stringify(detail);
}

// Access tokens are short-lived (30 minutes) while the httpOnly refresh
// cookie lasts 7 days. When a request fails with 401 mid-session, refresh the
// access token once and retry, so "Token has expired" only ever surfaces when
// the session is genuinely over.
let liveAccessToken = null;   // mirror of the AuthProvider's accessToken state
let refreshInFlight = null;   // dedupes concurrent refreshes
let tokenRefreshed = null;    // registered by AuthProvider: (token) => void
let sessionExpired = null;    // registered by AuthProvider: () => void

async function ensureFreshToken() {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const data = await api.refresh();
      const t = data.data?.access_token || data.access_token;
      if (!t) throw new Error("No session");
      liveAccessToken = t;
      if (tokenRefreshed) tokenRefreshed(t);
      return t;
    })();
    try {
      return await refreshInFlight;
    } finally {
      refreshInFlight = null;
    }
  }
  return refreshInFlight;
}

// Fetch with a bearer token; on 401 it refreshes once and retries. Returns
// the raw Response so callers can read JSON or a blob.
async function authedFetch(token, path, init = {}) {
  const run = (t) =>
    fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${t}` },
      credentials: "include",
    });

  const t = token || liveAccessToken;
  let res = await run(t);

  if (res.status === 401 && t) {
    try {
      res = await run(await ensureFreshToken());
    } catch (err) {
      // TypeError = network failure while refreshing: keep the original 401
      // for the caller to surface. Anything else means the refresh cookie is
      // dead too — end the session so the user is sent back to log in.
      if (!(err instanceof TypeError)) {
        liveAccessToken = null;
        if (sessionExpired) sessionExpired();
      }
    }
  }
  return res;
}

async function authFetch(path, opts = {}) {
  return parseResponse(
    await authedFetch(opts.accessToken, path, {
      method: opts.method,
      headers: jsonHeaders,
      body: opts.body != null ? JSON.stringify(opts.body) : undefined,
    })
  );
}

async function postJson(path, body) {
  return parseResponse(
    fetch(`${API_BASE}${path}`, {
      method: "POST",
      credentials: "include",
      headers: jsonHeaders,
      body: JSON.stringify(body),
    })
  );
}

const api = {
  // The API parses these bodies as Pydantic models, so they must be JSON —
  // urlencoded form data is rejected with 422.
  register: (body) =>
    postJson("/auth/register", {
      username: body.username || undefined,
      email: body.email,
      password: body.password,
      confirm_password: body.confirm_password,
    }),
  login: (body) => postJson("/auth/login", body),
  refresh: () =>
    parseResponse(
      fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      })
    ),
  me: (accessToken) =>
    parseResponse(
      fetch(`${API_BASE}/auth/me`, {
        credentials: "include",
        headers: { Authorization: `Bearer ${accessToken}` },
      })
    ),
  logout: () =>
    fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" }),
  products: (accessToken) => authFetch("/products", { accessToken }),
  product: (accessToken, product_id) =>
    authFetch(`/products/${product_id}`, { accessToken }),
  createProduct: (accessToken, body) =>
    authFetch("/products", { accessToken, method: "POST", body }),
  deleteProduct: (accessToken, id) =>
    authFetch(`/products/${id}`, { accessToken, method: "DELETE" }),
  versions: (accessToken, product_id) =>
    authFetch(`/products/${product_id}/versions`, { accessToken }),
  createVersion: (accessToken, product_id, body) =>
    authFetch(`/products/${product_id}/versions`, {
      accessToken,
      method: "POST",
      body,
    }),
  versionDetail: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}`, {
      accessToken,
    }),
  ingredients: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/ingredients`, {
      accessToken,
    }),
  createIngredient: (
    accessToken,
    product_id,
    version_id,
    body
  ) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/ingredients`,
      { accessToken, method: "POST", body }
    ),
  deleteIngredient: (
    accessToken,
    product_id,
    version_id,
    ingredient_id
  ) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/ingredients/${ingredient_id}`,
      { accessToken, method: "DELETE" }
    ),
  formulation: (accessToken, product_id, version_id) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/formulation`,
      { accessToken }
    ),
  upsertFormulation: (
    accessToken,
    product_id,
    version_id,
    body
  ) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/formulation`,
      { accessToken, method: "PUT", body }
    ),
  claims: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/claims`, {
      accessToken,
    }),
  createClaim: (accessToken, product_id, version_id, body) =>
    authFetch(`/products/${product_id}/versions/${version_id}/claims`, {
      accessToken,
      method: "POST",
      body,
    }),
  deleteClaim: (accessToken, product_id, version_id, claim_id) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/claims/${claim_id}`,
      { accessToken, method: "DELETE" }
    ),
  evidence: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/evidence`, {
      accessToken,
    }),
  createEvidence: (
    accessToken,
    product_id,
    version_id,
    body
  ) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/evidence`,
      { accessToken, method: "POST", body }
    ),
  targetMarkets: (accessToken, product_id, version_id) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/target-markets`,
      { accessToken }
    ),
  createTargetMarket: (
    accessToken,
    product_id,
    version_id,
    body
  ) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/target-markets`,
      { accessToken, method: "POST", body }
    ),
  deleteTargetMarket: (
    accessToken,
    product_id,
    version_id,
    market_id
  ) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/target-markets/${market_id}`,
      { accessToken, method: "DELETE" }
    ),
  // ---- Phase 4: Knowledge Base & RAG Assistant ----
  knowledgeStatus: (accessToken) => authFetch("/knowledge/status", { accessToken }),
  knowledgeDocuments: (accessToken, params = "") =>
    authFetch(`/knowledge/documents${params ? `?${params}` : ""}`, { accessToken }),
  uploadDocument: (accessToken, formData) =>
    parseResponse(
      authedFetch(accessToken, "/knowledge/documents", {
        method: "POST",
        body: formData,
      })
    ),
  deleteDocument: (accessToken, id) =>
    authFetch(`/knowledge/documents/${id}`, { accessToken, method: "DELETE" }),
  reindexDocument: (accessToken, id) =>
    authFetch(`/knowledge/documents/${id}/reindex`, { accessToken, method: "POST" }),
  chat: (accessToken, body) =>
    authFetch("/assistant/chat", { accessToken, method: "POST", body }),
  uploadChatAttachment: (accessToken, formData) =>
    parseResponse(
      authedFetch(accessToken, "/assistant/attachments", {
        method: "POST",
        body: formData,
      })
    ),
  conversations: (accessToken) =>
    authFetch("/assistant/conversations", { accessToken }),
  conversationDetail: (accessToken, id) =>
    authFetch(`/assistant/conversations/${id}`, { accessToken }),
  deleteConversation: (accessToken, id) =>
    authFetch(`/assistant/conversations/${id}`, { accessToken, method: "DELETE" }),
  // ---- Phase 5: analyses ----
  analyzeClaims: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/claims/analyze`, {
      accessToken,
      method: "POST",
    }),
  analyzeProduct: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/analyze`, {
      accessToken,
      method: "POST",
    }),
  analyses: (accessToken, product_id, version_id, analysis_type = "") =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/analyses${
        analysis_type ? `?analysis_type=${analysis_type}` : ""
      }`,
      { accessToken }
    ),
  analysisDetail: (accessToken, product_id, version_id, analysis_id) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/analyses/${analysis_id}`,
      { accessToken }
    ),
  // ---- Phase 6: IP routes, patent screening, biodiversity/ABS, TK ----
  ipRoutes: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/ip-routes`, {
      accessToken,
    }),
  patentSearch: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/patents/search`, {
      accessToken,
      method: "POST",
    }),
  patents: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/patents`, {
      accessToken,
    }),
  patentCompare: (accessToken, product_id, version_id, body = {}) =>
    authFetch(`/products/${product_id}/versions/${version_id}/patents/compare`, {
      accessToken,
      method: "POST",
      body,
    }),
  patentDetail: (accessToken, patent_id) =>
    authFetch(`/patents/${patent_id}`, { accessToken }),
  biodiversityScreen: (accessToken, product_id, version_id, includeSources = false) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/biodiversity/screen${
        includeSources ? "?include_sources=true" : ""
      }`,
      { accessToken, method: "POST" }
    ),
  tkScreen: (accessToken, product_id, version_id, includeSources = false) =>
    authFetch(
      `/products/${product_id}/versions/${version_id}/traditional-knowledge/screen${
        includeSources ? "?include_sources=true" : ""
      }`,
      { accessToken, method: "POST" }
    ),
  tkSources: (accessToken) =>
    authFetch("/traditional-knowledge/sources", { accessToken }),
  // ---- Phase 7: change impact ----
  changeImpact: (accessToken, product_id, body) =>
    authFetch(`/products/${product_id}/change-impact`, {
      accessToken,
      method: "POST",
      body,
    }),
  changeImpacts: (accessToken, product_id) =>
    authFetch(`/products/${product_id}/change-impact`, { accessToken }),
  changeImpactDetail: (accessToken, product_id, impact_id) =>
    authFetch(`/products/${product_id}/change-impact/${impact_id}`, { accessToken }),
  // ---- Phase 8: disclosures & reports ----
  disclosures: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/disclosures`, { accessToken }),
  createDisclosure: (accessToken, product_id, version_id, body) =>
    authFetch(`/products/${product_id}/versions/${version_id}/disclosures`, {
      accessToken, method: "POST", body,
    }),
  disclosureReview: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/disclosure-review`, {
      accessToken, method: "POST", body: {},
    }),
  genReport: (accessToken, product_id, version_id, kind) =>
    authFetch(`/products/${product_id}/versions/${version_id}/reports/${kind}`, {
      accessToken, method: "POST", body: {},
    }),
  reports: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/reports`, { accessToken }),
  downloadReport: async (accessToken, report_id) => {
    const res = await authedFetch(accessToken, `/reports/${report_id}`, {});
    if (!res.ok) throw new Error(`Download failed: ${res.status}`);
    return res.blob();
  },
  // ---- Overall Product View (spec item 16) ----
  productOverview: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/overview`, {
      accessToken,
    }),
  // ---- Phase 9: expert reviews ----
  reviews: (accessToken, status = "") =>
    authFetch(`/reviews${status ? `?status=${status}` : ""}`, { accessToken }),
  createReview: (accessToken, body) =>
    authFetch("/reviews", { accessToken, method: "POST", body }),
  reviewDetail: (accessToken, id) => authFetch(`/reviews/${id}`, { accessToken }),
  reviewAction: (accessToken, id, action, body = {}) =>
    authFetch(`/reviews/${id}/${action}`, { accessToken, method: "POST", body }),
  notifyReview: (accessToken, id) =>
    authFetch(`/reviews/${id}/notify`, { accessToken, method: "POST", body: {} }),
  // ---- Phase 10: home stat tiles & audit (backend /dashboard endpoint reused by Home) ----
  dashboard: (accessToken) => authFetch("/dashboard", { accessToken }),
  auditTrail: (accessToken) => authFetch("/audit", { accessToken }),
  // ---- Phase 11: BHASHINI ----
  bhashiniLanguages: (accessToken) => authFetch("/bhashini/languages", { accessToken }),
  bhashiniDetect: (accessToken, text) =>
    authFetch("/bhashini/detect", { accessToken, method: "POST", body: { text } }),
  bhashiniTranslate: (accessToken, body) =>
    authFetch("/bhashini/translate", { accessToken, method: "POST", body }),
  // ---- Clarifications (interactive classification loop) ----
  clarificationQuestions: (accessToken, product_id, version_id) =>
    authFetch(`/products/${product_id}/versions/${version_id}/clarification-questions`, {
      accessToken,
    }),
  answerClarification: (accessToken, product_id, version_id, body) =>
    authFetch(`/products/${product_id}/versions/${version_id}/clarifications`, {
      accessToken, method: "POST", body,
    }),
  // ---- Official sources registry + DPDP privacy ----
  officialSources: (accessToken, params = "") =>
    authFetch(`/official-sources${params}`, { accessToken }),
  officialSourceTopics: (accessToken) =>
    authFetch("/official-sources/topics", { accessToken }),
  officialSourceDetail: (accessToken, source_id) =>
    authFetch(`/official-sources/${encodeURIComponent(source_id)}`, { accessToken }),
  privacyNotice: (accessToken) => authFetch("/privacy/notice", { accessToken }),
  privacyConsents: (accessToken) => authFetch("/privacy/consent", { accessToken }),
  grantPrivacyConsent: (accessToken, body) =>
    authFetch("/privacy/consent", { accessToken, method: "POST", body }),
  grantSourceConsent: (accessToken, body) =>
    authFetch("/privacy/sources/consent", { accessToken, method: "POST", body }),
  revokeSourceConsent: (accessToken, consent_id) =>
    authFetch(`/privacy/sources/consent/${consent_id}`, { accessToken, method: "DELETE" }),
  requestSourceAccess: (accessToken, source_id) =>
    authFetch("/privacy/sources/access", { accessToken, method: "POST", body: { source_id } }),
  // ---- Knowledge graph + agent ----
  graphBuild: (accessToken, full = false) =>
    authFetch("/graph/build", { accessToken, method: "POST", body: { full } }),
  graphNodes: (accessToken, params = "") =>
    authFetch(`/graph/nodes${params}`, { accessToken }),
  graphNodeDetail: (accessToken, node_id) =>
    authFetch(`/graph/nodes/${node_id}`, { accessToken }),
  graphPaths: (accessToken, from, to) =>
    authFetch(`/graph/paths?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`, {
      accessToken,
    }),
  agentTools: (accessToken) => authFetch("/agent/tools", { accessToken }),
  agentRun: (accessToken, body) =>
    authFetch("/agent/run", { accessToken, method: "POST", body }),
  agentTraces: (accessToken) => authFetch("/agent/traces", { accessToken }),
  agentTraceDetail: (accessToken, run_id) =>
    authFetch(`/agent/traces/${run_id}`, { accessToken }),
};

// ---- Auth context --------------------------------------------------------

const AuthContext = createContext(null);

function AuthProvider({ children }) {
  const [accessToken, setAccessToken] = useState(null);
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState("checking");

  const refreshUser = useCallback(async (token) => {
    const me = await api.me(token);
    setUser(me.data?.username || me.data?.email || null);
  }, []);

  // Restore a session from the httpOnly refresh cookie instead of firing a
  // credential-less login (which the API correctly rejected with 422).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.refresh();
        const t = data.data?.access_token || data.access_token;
        if (!t) throw new Error("No session");
        await refreshUser(t);
        if (cancelled) return;
        setAccessToken(t);
        setStatus("authenticated");
      } catch {
        if (!cancelled) setStatus("anonymous");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshUser]);

  const login = useCallback(
    async (email, password) => {
      const data = await api.login({ email, password });
      const t = data.data?.access_token || data.access_token;
      if (!t) throw new Error("Login succeeded but no token was returned");
      setAccessToken(t);
      try {
        await refreshUser(t);
      } catch {
        setUser(null);
      }
      setStatus("authenticated");
    },
    [refreshUser]
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setAccessToken(null);
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  // Mirror the token for the fetch layer and register the hooks it uses when
  // an access token expires mid-session (refresh-retry, then forced re-login).
  useEffect(() => {
    liveAccessToken = accessToken;
  }, [accessToken]);

  useEffect(() => {
    tokenRefreshed = (t) => setAccessToken(t);
    sessionExpired = () => {
      liveAccessToken = null;
      setAccessToken(null);
      setUser(null);
      setStatus("anonymous");
    };
    return () => {
      tokenRefreshed = null;
      sessionExpired = null;
    };
  }, []);

  return (
    <AuthContext.Provider
      value={{ accessToken, user, status, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

// ---- Route guard ---------------------------------------------------------

// ---- Success toasts (green notification, auto-dismiss after 3s) ----------
const ToastContext = createContext(null);

function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = (id) => {
    setToasts((t) => t.map((x) => (x.id === id ? { ...x, closing: true } : x)));
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 240);
  };

  const toast = (message) => {
    const id = Math.random().toString(36).slice(2) + Date.now().toString(36);
    setToasts((t) => [...t.slice(-2), { id, message }]);
    setTimeout(() => dismiss(id), 3000);
  };

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={"toast" + (t.closing ? " out" : "")}>
            <span className="toast-ico" aria-hidden="true">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </span>
            <span className="toast-msg">{t.message}</span>
            <button
              type="button"
              className="toast-x"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

const useToast = () => useContext(ToastContext);

function ProtectedRoute({ children }) {
  const { status } = useAuth();
  if (status === "checking") return <p>Checking your session…</p>;
  if (status === "anonymous") return <Navigate to="/login" replace />;
  return children;
}

// ---- Shared UI -----------------------------------------------------------

const AUTH_CSS = `
.auth-lp { background: #FAF5EC; color: #1C2420; font-family: "Times New Roman", Times, serif; text-align: left; width: 100vw; margin-left: calc(50% - 50vw); min-height: 100svh; display: flex; flex-direction: column; }
.auth-lp h1, .auth-lp h2, .auth-lp p { color: #1C2420; margin: 0; }
.auth-lp-top { max-width: 1200px; margin: 0 auto; padding: 0 32px; width: 100%; box-sizing: border-box; }
.auth-lp-nav { display: flex; align-items: center; justify-content: space-between; height: 64px; border-bottom: 1px solid #E4DACA; }
.auth-lp-brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: #1C2420; font-weight: 700; }
.auth-lp-main { flex: 1; display: flex; align-items: center; justify-content: center; padding: 56px 24px; }
.auth-lp-card { background: #FFFDF8; border: 1px solid #E4DACA; border-radius: 10px; padding: 40px; width: 100%; max-width: 440px; box-shadow: 0 12px 32px -16px rgba(30,58,47,0.25); }
.auth-lp-card h1 { font-family: "Times New Roman", Times, serif; font-weight: 400; font-size: 32px; letter-spacing: -0.01em; margin: 0 0 8px; }
.auth-lp-sub { font-size: 15px; line-height: 1.6; color: #43524A; margin: 0 0 28px; }
.auth-lp-field { margin-bottom: 18px; }
.auth-lp-field label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 6px; }
.auth-lp-field input { width: 100%; box-sizing: border-box; min-height: 46px; padding: 0 14px; font-size: 16px; border: 1px solid #CBBFA6; border-radius: 6px; background: #fff; color: #1C2420; }
.auth-lp-field input:focus { outline: 3px solid #B98A2F; outline-offset: 1px; border-color: #1E3A2F; }
.auth-lp-help { font-size: 13px; color: #6B7280; margin-top: 6px; }
.auth-lp-pass { position: relative; }
.auth-lp-pass input { padding-right: 70px; }
.auth-lp-toggle { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); border: none; background: none; color: #1E3A2F; font-size: 13px; font-weight: 600; cursor: pointer; min-height: 36px; padding: 0 10px; }
.auth-lp-error { background: #FEF2F2; border: 1px solid #E5B4B4; color: #991B1B; font-size: 14px; border-radius: 6px; padding: 10px 14px; margin: 0 0 18px; }
.auth-lp-btn { width: 100%; min-height: 48px; border-radius: 999px; border: 1px solid #1E3A2F; background: #1E3A2F; color: #FAF5EC; font-size: 16px; font-weight: 600; cursor: pointer; transition: background 180ms ease; }
.auth-lp-btn:hover:not(:disabled) { background: #152A22; }
.auth-lp-btn:disabled { opacity: 0.55; cursor: default; }
.auth-lp-btn:focus-visible, .auth-lp-toggle:focus-visible, .auth-lp-brand:focus-visible { outline: 3px solid #B98A2F; outline-offset: 2px; }
.auth-lp-success { background: #F0FDF4; border: 1px solid #B7DFC0; color: #166534; font-size: 14px; border-radius: 6px; padding: 10px 14px; margin: 0 0 18px; }
.auth-lp-switch { font-size: 14px; color: #43524A; margin: 20px 0 0; text-align: center; }
.auth-lp-switch a { color: #1E3A2F; font-weight: 600; }
.auth-lp-foot { text-align: center; font-size: 12px; color: #8A8F88; padding: 0 24px 32px; }
@media (max-width: 520px) { .auth-lp-card { padding: 28px 22px; } }
`;

function AuthShell({ title, sub, children, foot }) {
  return (
    <div className="auth-lp">
      <style>{AUTH_CSS}</style>
      <div className="auth-lp-top">
        <div className="auth-lp-nav">
          <Link to="/" className="auth-lp-brand" aria-label="IP-SAKTI Sahayak home">
            <svg width="24" height="24" viewBox="0 0 26 26" fill="none" aria-hidden="true">
              <circle cx="13" cy="13" r="12" stroke="#1E3A2F" strokeWidth="1.5" />
              <path d="M13 19 C13 13 13 9 19 6 C19 12 17 17 13 19 Z" fill="#1E3A2F" />
              <path d="M13 19 C13 14 11 11 7 10 C8 14 10 17 13 19 Z" fill="#B98A2F" />
            </svg>
            <span>IP-SAKTI Sahayak</span>
          </Link>
          <Link to="/login" style={{ fontSize: "14px", fontWeight: 600, color: "#1E3A2F" }}>Sign in</Link>
        </div>
      </div>
      <main className="auth-lp-main">
        <div className="auth-lp-card">
          <h1>{title}</h1>
          <p className="auth-lp-sub">{sub}</p>
          {children}
        </div>
      </main>
    </div>
  );
}

function PasswordField({ id, label, value, onChange, help }) {
  const [show, setShow] = useState(false);
  return (
    <div className="auth-lp-field">
      <label htmlFor={id}>{label}</label>
      <div className="auth-lp-pass">
        <input id={id} type={show ? "text" : "password"} value={value}
          onChange={onChange} required autoComplete={id === "password" ? "new-password" : "new-password"} />
        <button type="button" className="auth-lp-toggle" onClick={() => setShow((s) => !s)}
          aria-label={show ? "Hide password" : "Show password"}>
          {show ? "Hide" : "Show"}
        </button>
      </div>
      {help && <p className="auth-lp-help">{help}</p>}
    </div>
  );
}

function Card({ children, title }) {
  return (
    <div className="card">
      {title && <h1 className="card-title">{title}</h1>}
      {children}
    </div>
  );
}

function Button({ children, onClick, variant = "primary", disabled, type = "submit", style }) {
  const cls =
    "btn " +
    (variant === "danger" ? "btn-danger" : variant === "ghost" ? "btn-ghost" : variant === "small" ? "btn-small" : "");
  return (
    <button className={cls} type={type} onClick={onClick} disabled={disabled} style={style}>
      {children}
    </button>
  );
}

// Prettify enum-style backend values for display: "official_guidance" -> "Official Guidance".
const prettify = (v) =>
  String(v ?? "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

function Badge({ text }) {
  return <span className="badge">{prettify(text)}</span>;
}

function Empty({ message }) {
  return <p className="empty">{message}</p>;
}

function Loading() {
  return <p className="empty">Loading…</p>;
}

function FormField({ label, id, type = "text", value, onChange, required }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={onChange}
        required={required}
      />
    </div>
  );
}

function FormError({ message }) {
  return message ? <p className="form-error">{message}</p> : null;
}

function FormSuccess({ message }) {
  return message ? <p className="form-success">{message}</p> : null;
}

// ---- Pages ----------------------------------------------------------------

function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email, password);
      navigate("/home");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell title="Welcome back" sub="Log in to continue to your Product Passports.">
      <form onSubmit={submit} noValidate={false}>
        <div className="auth-lp-field">
          <label htmlFor="login-email">Email</label>
          <input id="login-email" type="email" value={email}
            onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </div>
        <div className="auth-lp-field">
          <label htmlFor="login-password">Password</label>
          <div className="auth-lp-pass">
            <input id="login-password" type={show ? "text" : "password"} value={password}
              onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
            <button type="button" className="auth-lp-toggle" onClick={() => setShow((s) => !s)}
              aria-label={show ? "Hide password" : "Show password"}>
              {show ? "Hide" : "Show"}
            </button>
          </div>
        </div>
        {error && <p className="auth-lp-error" role="alert">{error}</p>}
        <button className="auth-lp-btn" disabled={loading}>{loading ? "Logging in…" : "Log in"}</button>
        <p className="auth-lp-switch">
          Don&apos;t have an account? <Link to="/register">Create one</Link>
        </p>
      </form>
    </AuthShell>
  );
}

function Register() {
  const navigate = useNavigate();
  const { login: signIn } = useAuth();
  const [form, setForm] = useState({ username: "", email: "", password: "", confirm_password: "" });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const field = (name) => (e) =>
    setForm((f) => ({ ...f, [name]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (form.password !== form.confirm_password) {
      setError("Passwords don't match");
      return;
    }
    if (form.password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setLoading(true);
    try {
      await api.register(form);
      setSuccess(true);
      try {
        await signIn(form.email, form.password);
        navigate("/home");
      } catch {
        navigate("/login");
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell title="Create your account" sub="One account for passports, screenings, disclosures and expert reviews.">
      <form onSubmit={submit}>
        <div className="auth-lp-field">
          <label htmlFor="reg-username">Username</label>
          <input id="reg-username" type="text" value={form.username}
            onChange={field("username")} required autoComplete="username" />
        </div>
        <div className="auth-lp-field">
          <label htmlFor="reg-email">Email</label>
          <input id="reg-email" type="email" value={form.email}
            onChange={field("email")} required autoComplete="email" />
        </div>
        <PasswordField id="reg-password" label="Password" value={form.password}
          onChange={field("password")} help="At least 8 characters." />
        <PasswordField id="reg-confirm" label="Confirm password" value={form.confirm_password}
          onChange={field("confirm_password")} />
        {error && <p className="auth-lp-error" role="alert">{error}</p>}
        {success && <p className="auth-lp-success" role="status">Account created — signing you in…</p>}
        <button className="auth-lp-btn" disabled={loading}>{loading ? "Creating account…" : "Create account"}</button>
        <p className="auth-lp-switch">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </form>
    </AuthShell>
  );
}

// ---- Layout --------------------------------------------------------------

function SideIcon({ d }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

function SideLink({ to, label, icon, collapsed }) {
  return (
    <NavLink to={to} title={collapsed ? label : undefined} className={({ isActive }) => "side-link" + (isActive ? " active" : "")}>
      <SideIcon d={icon} />
      {!collapsed && <span>{label}</span>}
    </NavLink>
  );
}

function Layout() {
  const { logout, user } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const name = user || "Account";
  const initial = (name.trim().charAt(0) || "A").toUpperCase();
  const { pathname } = useLocation();
  const links = [
    ["/products", "Products", "M21 8l-9-5-9 5v8l9 5 9-5V8zM3 8l9 5 9-5M12 13v8"],
    ["/knowledge", "Knowledge Base", "M4 19.5A2.5 2.5 0 0 1 6.5 17H20V4H6.5A2.5 2.5 0 0 0 4 6.5v13zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"],
    ["/chat", "Chatbot", "M21 12a8 8 0 0 1-8 8H5l-2 2V12a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8z"],
    ["/reviews", "Reviews", "M9 12l2 2 4-4M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z"],
    ["/overview", "Overall Product View", "M4 6h16M4 12h16M4 18h9"],
    ["/graph", "Knowledge Graph", "M12 2l9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5"],
  ];
  return (
    <div className="layout">
      <aside className={"sidebar" + (collapsed ? " collapsed" : "")}>
        <div className="side-top">
          <Link to="/home" className="brand" aria-label="IP-SAKTI Sahayak home">
            <svg width="26" height="26" viewBox="0 0 26 26" fill="none" aria-hidden="true">
              <circle cx="13" cy="13" r="12" stroke="#1E3A2F" strokeWidth="1.5" />
              <path d="M13 19 C13 13 13 9 19 6 C19 12 17 17 13 19 Z" fill="#1E3A2F" />
              <path d="M13 19 C13 14 11 11 7 10 C8 14 10 17 13 19 Z" fill="#B98A2F" />
            </svg>
            {!collapsed && <span>IP-SAKTI Sahayak</span>}
          </Link>
          <button className="side-toggle" onClick={() => setCollapsed((c) => !c)} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!collapsed} type="button">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={collapsed ? { transform: "rotate(180deg)" } : undefined}>
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
        </div>
        <nav className="side-nav" aria-label="Primary">
          {links.map(([to, label, icon]) => (
            <SideLink key={to} to={to} label={label} icon={icon} collapsed={collapsed} />
          ))}
        </nav>
        <div className="side-profile">
          <button className="profile-btn" onClick={() => setProfileOpen((o) => !o)} aria-expanded={profileOpen} type="button">
            <span className="avatar" aria-hidden="true">{initial}</span>
            {!collapsed && (
              <span className="profile-meta"><b>{name}</b><span>{profileOpen ? "Hide profile" : "View profile"}</span></span>
            )}
          </button>
          {profileOpen && (
            <div className="profile-menu">
              <p className="profile-id">{name}</p>
              <button className="btn btn-small" onClick={logout} type="button">Log out</button>
            </div>
          )}
        </div>
      </aside>
      <div className="side-content">
      <main className={"main" + (pathname === "/chat" ? " main-wide" : "")}>
        <Routes>
          <Route path="/home" element={<Home />} />
          <Route path="/products" element={<Products />} />
          <Route path="/products/new" element={<NewProduct />} />
          <Route path="/products/:id/versions" element={<Versions />} />
          <Route path="/products/:id/versions/:versionId" element={<VersionDetail />} />
          <Route path="/knowledge" element={<KnowledgeBase />} />
          <Route path="/chat" element={<ChatAssistant />} />
          <Route path="/reviews" element={<Reviews />} />
          <Route path="/overview" element={<OverallProductView />} />
          <Route path="/overview/:id/:versionId" element={<OverallProductView />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/demo" element={<Navigate to="/overview" replace />} />
        </Routes>
      </main>
      <style>{css}</style>
      </div>
    </div>
  );
}

const HM_CSS = `
.hm { font-family: "Times New Roman", Times, serif; color: #1C2420; text-align: left; width: 100%; max-width: 100%; margin: 0; background: #FAF5EC; position: relative; }
.hm h1, .hm h2, .hm p { margin: 0; }
.hm-inner { max-width: 1200px; margin: 0 auto; padding: 0 0 56px; }
.hm-top { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; flex-wrap: wrap; padding: 48px 0 8px; }
.hm-eyebrow { font-size: 12px; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase; color: #6B5E43; margin: 0 0 20px; }
.hm-h1 { font-family: "Times New Roman", Times, serif; font-weight: 400; font-size: clamp(32px, 3.8vw, 48px); line-height: 1.18; letter-spacing: -0.01em; color: #1C2420; margin: 0 0 18px; }
.hm-date { font-size: 14px; color: #6B7280; margin-top: 0; margin-bottom: 10px; }
.hm-cta { display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 26px; border-radius: 999px; background: #1E3A2F; color: #FAF5EC; font-size: 15px; font-weight: 700; text-decoration: none; border: 1px solid #1E3A2F; }
.hm-cta:hover { background: #152A22; }
.hm-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin: 28px 0; }
.hm-stat { background: #FFFDF8; border: 1px solid #E7DFCE; border-radius: 10px; padding: 22px; }
.hm-stat b { display: block; font-size: 34px; font-weight: 600; font-variant-numeric: tabular-nums; color: #1C2420; letter-spacing: -0.01em; }
.hm-stat span { font-size: 13px; color: #5B6670; display: block; margin-top: 6px; }
.hm-cols { display: grid; grid-template-columns: 1.2fr 1fr; gap: 16px; }
.hm-panel { background: #FFFDF8; border: 1px solid #E7DFCE; border-radius: 10px; padding: 26px; }
.hm-panel h2 { font-size: 16px; font-weight: 700; margin-bottom: 4px; color: #1C2420; }
.hm-panel .sub { font-size: 13px; color: #6B7280; margin-bottom: 8px; }
.hm-prod { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 14px 0; border-top: 1px solid #F0EAD9; text-decoration: none; color: inherit; }
.hm-prod b { font-size: 15px; color: #1C2420; }
.hm-prod span { font-size: 13px; color: #6B7280; display: block; margin-top: 2px; }
.hm-prod .go { color: #B98A2F; font-weight: 700; font-size: 14px; white-space: nowrap; }
.hm-empty { font-size: 14px; color: #6B7280; padding: 12px 0; }
.hm-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.hm-act { display: flex; gap: 12px; align-items: flex-start; border: 1px solid #E7DFCE; border-radius: 10px; padding: 16px; text-decoration: none; color: inherit; transition: border-color 180ms ease; background: #FFFDF8; }
.hm-act:hover { border-color: #1E3A2F; }
.hm-act svg { flex-shrink: 0; margin-top: 2px; }
.hm-act b { font-size: 14px; display: block; color: #1C2420; }
.hm-act span { font-size: 12.5px; color: #6B7280; display: block; margin-top: 2px; line-height: 1.5; }
.hm a:focus-visible, .hm-cta:focus-visible { outline: 3px solid #B98A2F; outline-offset: 2px; }
.hm-top.hm-hero { position: relative; overflow: hidden; background: linear-gradient(120deg, #F1E8D2 0%, #FAF5EC 55%, #E4ECE1 100%); border: 1px solid #E7DFCE; border-radius: 14px; padding: 40px 36px; margin-top: 32px; }
.hm-leaf { position: absolute; right: -34px; top: -34px; width: 230px; height: 230px; opacity: 0.12; pointer-events: none; }
.hm-attention { margin: 20px 0 0; padding: 12px 18px; background: #FFFDF8; border: 1px solid #E7DFCE; border-left: 4px solid #B98A2F; border-radius: 0 10px 10px 0; font-size: 14.5px; color: #1C2420; }
.hm-feed { display: flex; flex-direction: column; }
.hm-feed .row-item { display: flex; align-items: center; gap: 10px; padding: 12px 0; border-top: 1px solid #F0EAD9; font-size: 13.5px; color: #1C2420; }
.hm-feed .row-item:first-child { border-top: none; }
.hm-feed .row-meta { margin-left: auto; color: #6B7280; font-size: 12.5px; white-space: nowrap; }
@media (max-width: 900px) { .hm-stats { grid-template-columns: repeat(2, 1fr); } .hm-cols { grid-template-columns: 1fr; } .hm-top.hm-hero { padding: 28px 22px; } .hm-leaf { width: 150px; height: 150px; } }
`;
function Home() {
  const { accessToken, user } = useAuth();
  const [stats, setStats] = useState(null);
  const [products, setProducts] = useState([]);

  useEffect(() => {
    (async () => {
      try { setStats((await api.dashboard(accessToken)).data || null); }
      catch { setStats(null); }
      try { setProducts(((await api.products(accessToken)).data || []).slice(0, 4)); }
      catch { setProducts([]); }
    })();
  }, [accessToken]);

  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const tiles = [
    [stats?.product_count ?? "–", "Product passports"],
    [stats?.version_count ?? "–", "Tracked versions"],
    [stats?.pending_reviews ?? "–", "Reviews awaiting action"],
    [stats?.claims_needing_evidence ?? "–", "Claims needing evidence"],
  ];
  const needs = [];
  if ((stats?.claims_needing_evidence ?? 0) > 0) needs.push(`${stats.claims_needing_evidence} claim${stats.claims_needing_evidence === 1 ? "" : "s"} needing evidence`);
  if ((stats?.pending_reviews ?? 0) > 0) needs.push(`${stats.pending_reviews} review${stats.pending_reviews === 1 ? "" : "s"} awaiting action`);
  const attention = needs.length > 0 ? `Needs attention: ${needs.join(" · ")}.` : null;
  const feed = (stats?.recent_activity || []).slice(0, 5);

  return (
    <div className="hm">
      <style>{HM_CSS}</style>
      <div className="hm-inner">
      <div className="hm-top hm-hero">
        <svg className="hm-leaf" viewBox="0 0 26 26" fill="none" aria-hidden="true">
          <circle cx="13" cy="13" r="12" stroke="#1E3A2F" strokeWidth="1" />
          <path d="M13 19 C13 13 13 9 19 6 C19 12 17 17 13 19 Z" fill="#1E3A2F" />
          <path d="M13 19 C13 14 11 11 7 10 C8 14 10 17 13 19 Z" fill="#B98A2F" />
        </svg>
        <div>
          <p className="hm-eyebrow">Workspace</p>
          <h1 className="hm-h1">{greeting}.</h1>
          <p className="hm-date">{today}{user ? `  ·  Signed in as ${user}` : ""}</p>
        </div>
        <Link to="/products/new" className="hm-cta">+ New product</Link>
      </div>
      {attention && <p className="hm-attention">{attention}</p>}

      <div className="hm-stats">
        {tiles.map(([v, l]) => (
          <div className="hm-stat" key={l}><b>{v}</b><span>{l}</span></div>
        ))}
      </div>

      <div className="hm-cols">
        <div className="hm-panel">
          <h2>Recent products</h2>
          <p className="sub">Pick up where you left off.</p>
          {products.length === 0 && <p className="hm-empty">No products yet — create your first passport to begin.</p>}
          {products.map((p) => (
            <Link key={p.id} to={`/products/${p.id}/versions`} className="hm-prod">
              <div><b>{p.name}</b><span>{p.description || "No description"}</span></div>
              <span className="go">Open →</span>
            </Link>
          ))}
        </div>
        <div className="hm-panel">
          <h2>Recent activity</h2>
          <p className="sub">Latest moves across your workspace.</p>
          {stats && feed.length === 0 && <p className="hm-empty">Nothing recorded yet — activity appears here as you work.</p>}
          <div className="hm-feed">
            {feed.map((a) => (
              <div className="row-item" key={a.id}>
                <Badge text={a.action} />
                <span>{prettify(a.resource)} #{a.resource_id}</span>
                {a.timestamp && (
                  <span className="row-meta">
                    {new Date(a.timestamp).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
      </div>
    </div>
  );
}
const PL_CSS = `
  .pl { padding-top: 6px; }
  .pl-title { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
  .pl-title .pg-h1 { margin-bottom: 8px; }
  .pl-card { padding-top: 10px; }
  .pl-list { list-style: none; padding: 0; margin: 0; }
  .pl-item { display: flex; align-items: center; gap: 18px; padding: 17px 4px; border-top: 1px solid #F0EAD9; transition: background 160ms ease; border-radius: 6px; }
  .pl-item:first-child { border-top: none; }
  .pl-item:hover { background: #FAF7EF; }
  .pl-mark { width: 44px; height: 44px; border-radius: 50%; background: #FAF5EC; border: 1px solid #E4DACA; color: #1E3A2F; font-family: "Times New Roman", Times, serif; font-size: 18px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; text-transform: uppercase; }
  .pl-body { flex: 1; min-width: 0; }
  .pl-name { display: block; font-size: 15px; font-weight: 600; color: #1C2420; line-height: 1.4; }
  .pl-desc { margin: 4px 0 0; font-size: 13.5px; color: #5B6670; line-height: 1.5; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; }
  .pl-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin-top: 7px; font-size: 12.5px; color: #6B7280; }
  .pl-meta .badge { margin-left: 0; }
  .pl-actions { display: flex; gap: 8px; flex-shrink: 0; }
  .pl-empty { color: #5B6670; font-size: 14px; margin: 14px 0 6px; }
  .pl-error { margin: 0 0 8px; }
  @media (max-width: 760px) {
    .pl-title { flex-direction: column; align-items: flex-start; }
    .pl-item { flex-wrap: wrap; }
    .pl-actions { width: 100%; justify-content: flex-end; }
  }
`;

function Products() {
  const { accessToken } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await api.products(accessToken);
        setProducts(res.data || []);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [accessToken]);

  if (loading) return <Loading />;

  return (
    <div className="pl">
      <style>{PL_CSS}</style>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "12px" }}>
        <Button onClick={() => navigate("/products/new")}>New product</Button>
      </div>

      <div className="card pl-card">
        {error && <p className="form-error pl-error">{error}</p>}
        {products.length === 0 ? (
          <p className="pl-empty">
            No products yet — create your first passport to get started.
          </p>
        ) : (
          <ul className="pl-list">
            {products.map((p) => {
              const created = p.created_at ? new Date(p.created_at) : null;
              const dateText =
                created && !Number.isNaN(created.getTime())
                  ? created.toLocaleDateString("en-IN", {
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    })
                  : "";
              return (
                <li key={p.id} className="pl-item">
                  <div className="pl-mark">{(p.name || "?").charAt(0)}</div>
                  <div className="pl-body">
                    <span className="pl-name">{p.name}</span>
                    {p.description && <p className="pl-desc">{p.description}</p>}
                    <div className="pl-meta">
                      {p.category ? <Badge text={p.category} /> : null}
                      <span>
                        {p.version_count ?? 0} version
                        {p.version_count === 1 ? "" : "s"}
                      </span>
                      {dateText && <span>Created {dateText}</span>}
                    </div>
                  </div>
                  <div className="pl-actions">
                    <Button
                      variant="ghost"
                      small
                      onClick={() => navigate(`/products/${p.id}/versions`)}
                    >
                      Versions →
                    </Button>
                    <Button variant="danger" small onClick={() => {
                      if (!window.confirm(`Delete "${p.name}"?`)) return;
                      setError("");
                      api.deleteProduct(accessToken, p.id)
                        .then(() => {
                          setProducts((prev) => prev.filter((x) => x.id !== p.id));
                          toast("Product removed successfully");
                        })
                        .catch((err) => setError(err.message));
                    }}>
                      Delete
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

const NP_CSS = `
  .np { padding-top: 6px; }
  .np-grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 18px; align-items: start; }
  .np-form { padding: 30px 32px; }
  .np-form .field textarea { width: 100%; padding: 11px 13px; border: 1px solid #E4DACA; border-radius: 8px; font-size: 14.5px; font-family: inherit; background: #FAF5EC; color: #1C2420; resize: vertical; }
  .np-form .field textarea::placeholder { color: #9AA29E; }
  .np-form .field textarea:focus { outline: 2px solid #1E3A2F; outline-offset: 1px; border-color: transparent; }
  .np-hint { font-size: 12.5px; line-height: 1.5; color: #6B7280; margin: 7px 0 0; }
  .np-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; padding-top: 20px; border-top: 1px solid #F0EAD9; }
  .np-side h2 { margin: 0 0 16px; font-size: 12px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: #6B5E43; }
  .np-steps { list-style: none; counter-reset: np-step; padding: 0; margin: 0; }
  .np-steps li { counter-increment: np-step; position: relative; padding: 0 0 18px 40px; font-size: 13.5px; line-height: 1.55; color: #5B6670; }
  .np-steps li:last-child { padding-bottom: 4px; }
  .np-steps li::before { content: counter(np-step); position: absolute; left: 0; top: -2px; width: 26px; height: 26px; border-radius: 50%; background: #FAF5EC; border: 1px solid #E4DACA; color: #1E3A2F; font-size: 12px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
  .np-steps li:not(:last-child)::after { content: ""; position: absolute; left: 13px; top: 26px; bottom: 2px; width: 1px; background: #E4DACA; }
  .np-steps li b { display: block; font-size: 14px; color: #1C2420; margin-bottom: 2px; }
  .np-note { margin: 16px 0 0; padding: 13px 15px; background: #FAF5EC; border: 1px solid #E7DFCE; border-radius: 8px; font-size: 12.5px; line-height: 1.6; color: #6B5E43; }
  .np-actions .form-error { margin: 0 auto 0 0; align-self: center; }
  @media (max-width: 980px) { .np-grid { grid-template-columns: 1fr; } }
`;

// Display labels for the backend's lowercase category enum — values must stay
// exactly as the API expects them; only the text shown to the user is prettified.
const NP_CATEGORIES = [
  ["classical_traditional", "Classical / traditional"],
  ["proprietary_ayurvedic", "Proprietary ayurvedic"],
  ["possible_medicinal", "Possible medicinal"],
  ["ayurveda_aahara", "Ayurveda aahara (food)"],
  ["possible_cosmetic", "Possible cosmetic"],
  ["research_product", "Research product"],
  ["industrial_product", "Industrial product"],
];

function NewProduct() {
  const navigate = useNavigate();
  const { accessToken } = useAuth();
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (!name.trim()) return setError("Name is required");
    setLoading(true);
    try {
      const data = await api.createProduct(accessToken, {
        name: name.trim(),
        description: description.trim() || null,
        category: category || null,
      });
      setSuccess(true);
      toast("Product created successfully");
      const id = data.data?.id;
      if (id) navigate(`/products/${id}/versions`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="np">
      <style>{NP_CSS}</style>
      <header className="pg-head">
        <p className="pg-eyebrow">Product passport</p>
        <h1 className="pg-h1">Create a new product.</h1>
        <p className="pg-sub">
          Record it once — the details below become version 1 of the product&apos;s passport.
          Every change after this is tracked as a new version you can compare, review and verify.
        </p>
      </header>

      <div className="np-grid">
        <form className="card np-form" onSubmit={submit}>
          <FormField label="Product name" id="name" value={name} onChange={(e) => setName(e.target.value)} required />
          <div className="field">
            <label htmlFor="desc">Description (optional)</label>
            <textarea id="desc" rows={3} value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What is this product, and who is it for?" />
          </div>
          <div className="field">
            <label htmlFor="category">Category</label>
            <select id="category" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">None — decide later</option>
              {NP_CATEGORIES.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <p className="np-hint">Optional. Shapes the preliminary classification and the IP screenings — you can set it at any time.</p>
          </div>
          <FormSuccess message={success ? "Product created — taking you to version 1…" : null} />
          <div className="np-actions">
            <FormError message={error} />
            <Button variant="ghost" type="button" onClick={() => navigate(-1)}>Cancel</Button>
            <Button disabled={loading}>{loading ? "Creating…" : "Create product"}</Button>
          </div>
        </form>

        <aside className="card np-side">
          <h2>What happens next</h2>
          <ol className="np-steps">
            <li><b>Version 1 is created</b>A clean baseline that every future version is compared against.</li>
            <li><b>Add your content</b>Ingredients, formulation, claims, evidence and target markets.</li>
            <li><b>Ask for evidence</b>Run claim analysis, the IP route map and the screenings.</li>
            <li><b>Track every change</b>New formulation or claim? Save it as a new version and compare.</li>
          </ol>
          <p className="np-note">
            Nothing here is final — content stays editable, and every edit is snapshotted and
            SHA-256 hashed so the record always shows what changed.
          </p>
        </aside>
      </div>
    </div>
  );
}

// ---- Versions ------------------------------------------------------------

const VR_CSS = `
  .vr { padding-top: 6px; }
  .vr-grid { display: grid; grid-template-columns: 1.5fr 1fr; gap: 18px; align-items: start; }
  .vr-main { min-width: 0; }
  .vr-impact { margin-top: 18px; }
  .vr-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
  .vr-head h2 { margin: 0; font-size: 16px; font-weight: 700; color: #1C2420; }
  .vr-count { font-size: 11.5px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; color: #6B5E43; white-space: nowrap; }
  .vr-empty { color: #5B6670; font-size: 14px; margin: 12px 0 4px; }
  .vr-list { list-style: none; padding: 0; margin: 6px 0 0; }
  .vr-item { display: flex; align-items: center; gap: 16px; padding: 15px 2px; border-top: 1px solid #F0EAD9; transition: background 160ms ease; border-radius: 6px; }
  .vr-item:first-child { border-top: none; }
  .vr-item:hover { background: #FAF7EF; }
  .vr-num { font-family: "Times New Roman", Times, serif; font-size: 21px; color: #1E3A2F; min-width: 52px; flex-shrink: 0; }
  .vr-body { flex: 1; min-width: 0; }
  .vr-reason { margin: 0; font-size: 14.5px; font-weight: 600; color: #1C2420; line-height: 1.4; }
  .vr-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin-top: 5px; font-size: 12.5px; color: #6B7280; }
  .vr-hash { font-family: "Times New Roman", Times, serif; color: #6B5E43; }
  .vr-tag { display: inline-block; padding: 2px 9px; border-radius: 999px; background: #1E3A2F; color: #FAF5EC; font-size: 9.5px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; }
  .vr-open { flex-shrink: 0; border: 1px solid #E4DACA; background: #FFFDF8; color: #1E3A2F; font-size: 13px; font-weight: 700; padding: 8px 17px; border-radius: 999px; cursor: pointer; transition: border-color 160ms ease, background 160ms ease, transform 160ms ease; }
  .vr-open:hover { border-color: #1E3A2F; background: #F5EEDF; transform: translateY(-1px); }
  .vr-new h2 { margin: 0 0 18px; font-size: 12px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: #6B5E43; }
  .nvf-hint { font-size: 12.5px; line-height: 1.5; color: #6B7280; margin: 7px 0 0; }
  .nvf .field { margin-bottom: 16px; }
  .nvf .btn { width: 100%; margin-top: 4px; }
  .nvf .form-error { margin: 0 0 10px; }
  @media (max-width: 980px) { .vr-grid { grid-template-columns: 1fr; } }
`;

function Versions() {
  const { id } = useParams();
  const { accessToken } = useAuth();
  const navigate = useNavigate();
  const [product, setProduct] = useState(null);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const data = await api.versions(accessToken, Number(id));
        setVersions(data.data || []);
      } catch {
        setVersions([]);
      } finally {
        setLoading(false);
      }
    })();
    (async () => {
      try {
        setProduct((await api.product(accessToken, Number(id))).data || null);
      } catch {
        setProduct(null);
      }
    })();
  }, [accessToken, id]);

  if (loading) return <Loading />;

  const latestNumber = versions.reduce(
    (max, v) => Math.max(max, Number(v.version_number) || 0),
    0
  );

  return (
    <div className="vr">
      <style>{VR_CSS}</style>
      <header className="pg-head">
        <p className="pg-eyebrow">Product passport · Versions</p>
        <h1 className="pg-h1">{product?.name || "Versions"}</h1>
        <p className="pg-sub">
          Every version is a snapshot of the passport&apos;s content with its own SHA-256
          hash. Create a new one whenever the formulation, claims or markets change — the
          previous record stays untouched.
        </p>
      </header>

      <div className="vr-grid">
        <div className="vr-main">
          <section className="card">
            <div className="vr-head">
              <h2>Versions</h2>
              <span className="vr-count">
                {versions.length} recorded
              </span>
            </div>
            {versions.length === 0 ? (
              <p className="vr-empty">No versions yet — create the first snapshot of this passport.</p>
            ) : (
              <ul className="vr-list">
                {versions.map((v) => {
                  const created = v.created_at ? new Date(v.created_at) : null;
                  const dateText =
                    created && !Number.isNaN(created.getTime())
                      ? created.toLocaleDateString("en-IN", {
                          day: "numeric",
                          month: "short",
                          year: "numeric",
                        })
                      : "";
                  const isLatest = (Number(v.version_number) || 0) === latestNumber;
                  return (
                    <li key={v.id} className="vr-item">
                      <div className="vr-num">v{v.version_number}</div>
                      <div className="vr-body">
                        <p className="vr-reason">{v.change_reason || `Version ${v.version_number}`}</p>
                        <div className="vr-meta">
                          {dateText && <span>{dateText}</span>}
                          <span className="vr-hash">
                            {v.content_hash
                              ? `SHA-256 · ${v.content_hash.slice(0, 12)}…`
                              : "hash pending"}
                          </span>
                          {isLatest && <span className="vr-tag">Latest</span>}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="vr-open"
                        onClick={() => navigate(`/products/${id}/versions/${v.id}`)}
                      >
                        Open →
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>

        <aside className="card vr-new">
          <h2>New version</h2>
          <NewVersionForm
            accessToken={accessToken}
            productId={Number(id)}
            navigate={navigate}
          />
        </aside>
      </div>

      <div className="vr-impact">
        <ChangeImpactCard
          accessToken={accessToken}
          productId={Number(id)}
          versions={versions}
        />
      </div>
    </div>
  );
}

function NewVersionForm({ accessToken, productId, navigate }) {
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [empty, setEmpty] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.createVersion(accessToken, productId, {
        change_reason: reason.trim() || "New version",
        start_empty: empty,
      });
      toast("Version created successfully");
      navigate(`/products/${productId}/versions/${data.data?.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="nvf" onSubmit={submit}>
      <div className="field">
        <label htmlFor="nv-reason">Change reason</label>
        <input
          id="nv-reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Wild-collected material"
        />
        <p className="nvf-hint">
          Optional — defaults to “New version” and is stored on the record.
        </p>
      </div>
      <div className="field">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={empty}
            onChange={(e) => setEmpty(e.target.checked)}
          />
          Start empty — don&apos;t inherit the current content
        </label>
      </div>
      <FormError message={error} />
      <Button disabled={loading} type="submit">
        {loading ? "Creating…" : "Create version"}
      </Button>
    </form>
  );
}

// ---- Change impact (Phase 7) -----------------------------------------------

const CHANGE_CATEGORY_LABELS = {
  ingredients: "Ingredients",
  botanical: "Botanical species",
  plant_part: "Plant parts",
  quantities: "Quantities",
  origin: "Resource origin",
  cultivation: "Cultivation / wild status",
  formulation: "Formulation",
  extraction: "Extraction process",
  claims: "Claims",
  evidence: "Evidence",
  markets: "Target markets",
  public_disclosure: "Public disclosure",
  patent_signals: "Patent-related signals",
  biodiversity_tk: "Biodiversity / TK considerations",
  classification: "Product classification",
};

function ChangeImpactCard({ accessToken, productId, versions }) {
  const sorted = [...(versions || [])].sort((a, b) => a.version_number - b.version_number);
  const [oldId, setOldId] = useState("");
  const [newId, setNewId] = useState("");
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Default to the two newest versions, but never override a manual choice.
  useEffect(() => {
    if (!sorted.length) return;
    setOldId((prev) => prev || String(sorted[Math.max(0, sorted.length - 2)].id));
    setNewId((prev) => prev || String(sorted[sorted.length - 1].id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versions]);

  const load = useCallback(async () => {
    try {
      const res = await api.changeImpacts(accessToken, productId);
      setRuns(res.data || []);
    } catch (err) {
      setError(err.message);
    }
  }, [accessToken, productId]);

  useEffect(() => {
    load();
  }, [load]);

  const run = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await api.changeImpact(accessToken, productId, {
        old_version_id: Number(oldId),
        new_version_id: Number(newId),
      });
      setRuns((prev) => [res.data, ...prev]);
      setSelected(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const canRun = oldId && newId && oldId !== newId;
  const result = selected?.results;

  // Group the differences by category so the report reads like the master prompt.
  const grouped = {};
  (result?.changes || []).forEach((c) => {
    (grouped[c.category] = grouped[c.category] || []).push(c);
  });

  return (
    <Card title="Formulation change impact">
      <p className="muted">
        Compare two versions of this product. The report lists the differences between them,
        ranks their significance and raises review questions. It is advisory: it never edits a
        version and never states a legal, patent or regulatory conclusion.
      </p>

      <div className="change-toolbar">
        <label>
          From&nbsp;
          <select value={oldId} onChange={(e) => setOldId(e.target.value)}>
            <option value="">—</option>
            {sorted.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number}
              </option>
            ))}
          </select>
        </label>
        <label>
          To&nbsp;
          <select value={newId} onChange={(e) => setNewId(e.target.value)}>
            <option value="">—</option>
            {sorted.map((v) => (
              <option key={v.id} value={v.id}>
                v{v.version_number}
              </option>
            ))}
          </select>
        </label>
        <Button disabled={loading || !canRun} onClick={run} type="button">
          {loading ? "Comparing…" : "Compare versions"}
        </Button>
      </div>

      {sorted.length < 2 && (
        <p className="muted">Create a second version to compare.</p>
      )}
      {oldId && newId && oldId === newId && (
        <p className="muted">Choose two different versions.</p>
      )}
      {error && <p className="form-error">{error}</p>}

      {runs.length > 0 && (
        <div className="field">
          <label htmlFor="change-run">Recorded comparisons (newest first)</label>
          <select
            id="change-run"
            value={selected?.id ?? ""}
            onChange={(e) => setSelected(runs.find((r) => r.id === Number(e.target.value)) || null)}
          >
            <option value="">— pick a recorded run —</option>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                #{r.id} · {r.results?.summary || "(no summary)"}
              </option>
            ))}
          </select>
        </div>
      )}

      {result && (
        <div className="analysis-result">
          <div className="badge-row">
            <Badge text={`v${result.old_version_number} \u2192 v${result.new_version_number}`} />
            <Badge text={`${result.change_count} difference(s)`} />
            {result.expert_review_recommended && <Badge text="expert review recommended" />}
            {result.identical && <Badge text="identical content" />}
          </div>

          <p className="assessment-text">{result.summary}</p>

          {/* Spec item 10: what these changes mean for review. */}
          {result.affected_areas?.length > 0 && (
            <>
              <h3 className="subheading">Affected areas</h3>
              <div className="badge-row">
                {result.affected_areas.map((a) => (
                  <Badge key={a} text={a} />
                ))}
              </div>
            </>
          )}

          {result.reassessment_recommended?.length > 0 && (
            <>
              <h3 className="subheading">Re-assessment recommended</h3>
              <ul className="missing-list">
                {result.reassessment_recommended.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </>
          )}

          {result.missing_information?.length > 0 && (
            <>
              <h3 className="subheading">Missing information for these changes</h3>
              <ul className="missing-list">
                {result.missing_information.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            </>
          )}

          {result.expert_review_reasons?.length > 0 && (
            <>
              <h3 className="subheading">Why expert review is recommended</h3>
              <ul className="missing-list">
                {result.expert_review_reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            </>
          )}

          {Object.entries(grouped).map(([category, items]) => (
            <div key={category}>
              <h3 className="subheading">
                {CHANGE_CATEGORY_LABELS[category] || category} ({items.length})
              </h3>
              {items.map((c, i) => (
                <div key={i} className="assessment">
                  <div className="badge-row">
                    <Badge text={c.change_type} />
                    <Badge text={c.significance} />
                    <Badge text={c.field} />
                  </div>
                  {c.subject && <p className="assessment-text">{c.subject}</p>}
                  {(c.old_value || c.new_value) && (
                    <p className="assessment-rationale">
                      {c.change_type === "modified"
                        ? `${c.old_value ?? "—"} \u2192 ${c.new_value ?? "—"}`
                        : c.change_type === "added"
                        ? `added: ${c.new_value ?? "—"}`
                        : `removed: ${c.old_value ?? "—"}`}
                    </p>
                  )}
                  {c.note && <p className="muted">{c.note}</p>}
                </div>
              ))}
            </div>
          ))}

          {result.review_questions?.length > 0 && (
            <>
              <h3 className="subheading">Review questions</h3>
              {result.review_questions.map((q, i) => (
                <div key={i} className="assessment">
                  <p className="assessment-text">{q.question}</p>
                  {q.rationale && <p className="assessment-rationale">{q.rationale}</p>}
                </div>
              ))}
            </>
          )}

          {result.not_compared?.length > 0 && (
            <>
              <h3 className="subheading">Not compared by this run</h3>
              {result.not_compared.map((n, i) => (
                <div key={i} className="notice notice-info">
                  <strong>{CHANGE_CATEGORY_LABELS[n.category] || n.category}:</strong> {n.reason}
                </div>
              ))}
            </>
          )}

          {selected.warnings?.length > 0 && (
            <>
              <h3 className="subheading">Warnings &amp; disclaimers</h3>
              {selected.warnings.map((w, i) => (
                <div key={i} className="notice notice-warn">
                  {w}
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </Card>
  );
}

// ---- Version detail -------------------------------------------------------

const VD_CSS = `
  .vd { padding-top: 6px; }
  .vd-title { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
  .vd-title .pg-h1 { margin-bottom: 0; }
  .vd-title + .pg-sub { margin-top: 10px; }
  .vd-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; margin-top: 14px; }
  .vd-date { font-size: 12.5px; font-weight: 600; color: #6B7280; }
  .vd-hash { font-family: "Times New Roman", Times, serif; font-size: 12px; color: #6B5E43; background: #F3ECDC; border: 1px solid #E7DFCE; border-radius: 7px; padding: 5px 11px; word-break: break-all; max-width: 100%; }
  .vd-card { padding-top: 10px; }
  .vd .section { border-top: 1px solid #F0EAD9; padding: 24px 0; }
  .vd-card > .section:first-child { border-top: none; padding-top: 6px; }
  .vd .section:last-child { padding-bottom: 4px; }
  .vd .section-title { font-size: 11.5px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: #6B5E43; gap: 10px; margin-bottom: 14px; }
  .vd .section-title .badge { margin-left: 0; background: #1E3A2F; border-color: #1E3A2F; color: #FAF5EC; font-size: 9.5px; padding: 2px 8px; }
  .vd .section > .card-row { margin-bottom: 14px; }
  .vd .section > .card-row > div:empty { display: none; }
  .vd .inline-form { gap: 10px; padding: 15px 16px; background: #FAF7EF; border: 1px dashed #E4DACA; border-radius: 10px; }
  .vd .inline-form .input { width: auto; flex: 1 1 170px; min-width: 150px; padding: 10px 12px; border: 1px solid #E4DACA; border-radius: 8px; font-size: 14px; background: #FFFDF8; color: #1C2420; }
  .vd .inline-form .input::placeholder { color: #9AA29E; }
  .vd .inline-form .input:focus { outline: 2px solid #1E3A2F; outline-offset: 1px; border-color: transparent; }
  .vd .inline-form textarea { background: #FFFDF8; border-color: #E4DACA; border-radius: 8px; font-size: 14px; }
  .vd .inline-form .form-error { flex-basis: 100%; margin: 0; }
  .vd .list-item { border: none; border-top: 1px solid #F0EAD9; border-radius: 0; background: transparent; margin-bottom: 0; padding: 14px 2px; }
  .vd .list-item:first-child { border-top: none; }
  .vd .list-item:hover { background: #FAF7EF; box-shadow: none; }
  .vd .kv dt { font-size: 11.5px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #6B5E43; padding-top: 2px; }
  .vd .kv dd { color: #1C2420; white-space: pre-wrap; }
  .vd .empty { font-size: 13.5px; }
`;

function VersionDetail() {
  const { id, versionId } = useParams();
  const { accessToken } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [detail, setDetail] = useState(null);
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const d = await api.versionDetail(accessToken, Number(id), Number(versionId));
        setDetail(d.data || d);
      } catch {
        setDetail(null);
      } finally {
        setLoading(false);
      }
    })();
    (async () => {
      try {
        setProduct((await api.product(accessToken, Number(id))).data || null);
      } catch {
        setProduct(null);
      }
    })();
  }, [accessToken, id, versionId]);

  if (loading) return <Loading />;
  if (!detail)
    return (
      <div className="vd">
        <style>{VD_CSS}</style>
        <header className="pg-head">
          <p className="pg-eyebrow">Product passport</p>
          <h1 className="pg-h1">Version not found.</h1>
          <p className="pg-sub">
            This version may have been removed, or the link is out of date.
          </p>
        </header>
        <div className="card">
          <Button variant="ghost" onClick={() => navigate(`/products/${id}/versions`)}>
            Back to versions
          </Button>
        </div>
      </div>
    );

  const { ingredients = [], formulation, claims = [], evidence = [], target_markets = [] } = detail;

  const created = detail.created_at ? new Date(detail.created_at) : null;
  const createdText =
    created && !Number.isNaN(created.getTime())
      ? created.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
      : "";

  return (
    <div className="vd">
      <style>{VD_CSS}</style>
      <header className="pg-head">
        <p className="pg-eyebrow">
          Product passport · Version {detail.version_number}
        </p>
        <div className="vd-title">
          <h1 className="pg-h1">{product?.name || `Version ${detail.version_number}`}</h1>
          <Button variant="ghost" onClick={() => navigate(`/products/${id}/versions`)}>
            All versions
          </Button>
        </div>
        <p className="pg-sub">
          {detail.change_reason ||
            "Immutable snapshot of the passport's content — edits create a new version instead of changing this record."}
        </p>
        <div className="vd-meta">
          {createdText && <span className="vd-date">Created {createdText}</span>}
          <span className="vd-hash">
            {detail.content_hash ? `SHA-256 · ${detail.content_hash}` : "hash pending"}
          </span>
        </div>
      </header>

      <div className="card vd-card">
        <Section title="Formulation">
          <div className="card-row">
            <div></div>
            <UpsertFormulationForm {...(() => {
              const fb = {};
              fb.accessToken = accessToken;
              fb.productId = Number(id);
              fb.versionId = Number(versionId);
              fb.formulation = formulation;
              fb.setFormulation = (next) => setDetail((d) => ({ ...d, formulation: next }));
              return fb;
            })()} />
          </div>
          {!formulation ? (
            <Empty message="No formulation recorded yet — describe the process above and save." />
          ) : (
            <dl className="kv">
              {Object.entries(formulation)
                .filter(
                  ([k, v]) =>
                    v != null && v !== "" && k !== "id" && k !== "product_version_id"
                )
                .map(([k, v]) => (
                  <div key={k}>
                    <dt>{k.replace(/_/g, " ")}</dt>
                    <dd>
                      {k.endsWith("_at") && !Number.isNaN(new Date(v).getTime())
                        ? new Date(v).toLocaleString("en-IN", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : String(v)}
                    </dd>
                  </div>
                ))}
            </dl>
          )}
        </Section>

        <Section title="Ingredients" badge={ingredients.length}>
          <div className="card-row">
            <div></div>
            <AddIngredientForm {...(() => {
              const fb = {};
              fb.accessToken = accessToken;
              fb.productId = Number(id);
              fb.versionId = Number(versionId);
              fb.setIngredients = (next) => setDetail((d) => ({
                ...d,
                ingredients: typeof next === "function" ? next(d.ingredients) : next,
              }));
              return fb;
            })()} />
          </div>
          {ingredients.length === 0 ? (
            <Empty message="No ingredients yet. Add one above." />
          ) : (
            <ul className="list">
              {ingredients.map((ing) => (
                <li key={ing.id} className="list-item">
                  <div className="item-body">
                    <strong>{ing.common_name}</strong>
                    {ing.botanical_name && <p>{ing.botanical_name}</p>}
                    {ing.sanskrit_name && <Badge text={ing.sanskrit_name} />}
                    {ing.plant_part && <Badge text={ing.plant_part} />}
                    {ing.quantity != null && (
                      <span>
                        {ing.quantity} {ing.quantity_unit}
                      </span>
                    )}
                    {ing.source_type && <Badge text={ing.source_type} />}
                    {ing.source_location && (
                      <span className="muted">Source location: {ing.source_location}</span>
                    )}
                    <span className="muted">{ing.provenance}</span>
                  </div>
                  <Button
                    variant="danger"
                    small
                    onClick={() => {
                      api.deleteIngredient(accessToken, Number(id), Number(versionId), ing.id)
                        .then(() => {
                          setDetail((d) => ({
                            ...d,
                            ingredients: d.ingredients.filter((x) => x.id !== ing.id),
                          }));
                          toast("Ingredient removed successfully");
                        })
                        .catch((err) => alert(err.message));
                    }}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Claims" badge={claims.length}>
          <div className="card-row">
            <div></div>
            <AddClaimForm {...(() => {
              const fb = {};
              fb.accessToken = accessToken;
              fb.productId = Number(id);
              fb.versionId = Number(versionId);
              fb.setClaims = (next) => setDetail((d) => ({
                ...d,
                claims: typeof next === "function" ? next(d.claims) : next,
              }));
              return fb;
            })()} />
          </div>
          {claims.length === 0 ? (
            <Empty message="No claims yet." />
          ) : (
            <ul className="list">
              {claims.map((c) => (
                <li key={c.id} className="list-item">
                  <div className="item-body">
                    <p>{c.claim_text}</p>
                    {c.claim_type && <Badge text={c.claim_type} />}
                    {c.evidence_status && <Badge text={c.evidence_status} />}
                    {c.review_status && <Badge text={c.review_status} />}
                    {c.evidence_notes && <p className="muted">{c.evidence_notes}</p>}
                    <span className="muted">{c.provenance}</span>
                  </div>
                  <Button
                    variant="danger"
                    small
                    onClick={() => {
                      api.deleteClaim(accessToken, Number(id), Number(versionId), c.id)
                        .then(() => {
                          setDetail((d) => ({
                            ...d,
                            claims: d.claims.filter((x) => x.id !== c.id),
                          }));
                          toast("Claim removed successfully");
                        })
                        .catch((err) => alert(err.message));
                    }}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Evidence" badge={evidence.length}>
          <div className="card-row">
            <div></div>
            <AddEvidenceForm {...(() => {
              const fb = {};
              fb.accessToken = accessToken;
              fb.productId = Number(id);
              fb.versionId = Number(versionId);
              fb.setEvidence = (next) => setDetail((d) => ({
                ...d,
                evidence: typeof next === "function" ? next(d.evidence) : next,
              }));
              return fb;
            })()} />
          </div>
          {evidence.length === 0 ? (
            <Empty message="No evidence attached yet." />
          ) : (
            <ul className="list">
              {evidence.map((e) => (
                <li key={e.id} className="list-item">
                  <div className="item-body">
                    <strong>{e.title}</strong>
                    {e.evidence_type && <Badge text={e.evidence_type} />}
                    {e.doi && <span className="muted">DOI: {e.doi}</span>}
                    {e.publication_date && <span className="muted">{e.publication_date}</span>}
                    {e.authors && <span className="muted">{e.authors}</span>}
                    {e.verification_status && <Badge text={e.verification_status} />}
                    <span className="muted">{e.provenance}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Target markets" badge={target_markets.length}>
          <div className="card-row">
            <div></div>
            <AddTargetMarketForm {...(() => {
              const fb = {};
              fb.accessToken = accessToken;
              fb.productId = Number(id);
              fb.versionId = Number(versionId);
              fb.setTargetMarkets = (next) => setDetail((d) => ({
                ...d,
                target_markets: typeof next === "function" ? next(d.target_markets) : next,
              }));
              return fb;
            })()} />
          </div>
          {target_markets.length === 0 ? (
            <Empty message="No markets specified yet." />
          ) : (
            <ul className="list">
              {target_markets.map((m) => (
                <li key={m.id} className="list-item">
                  <div className="item-body">
                    <strong>{m.country}</strong>
                    {m.region && <Badge text={`region: ${m.region}`} />}
                    {m.regulatory_status && <Badge text={m.regulatory_status} />}
                    {m.notes && <p>{m.notes}</p>}
                  </div>
                  <Button
                    variant="danger"
                    small
                    onClick={() => {
                      api.deleteTargetMarket(accessToken, Number(id), Number(versionId), m.id)
                        .then(() => {
                          setDetail((d) => ({
                            ...d,
                            target_markets: d.target_markets.filter((x) => x.id !== m.id),
                          }));
                          toast("Target market removed successfully");
                        })
                        .catch((err) => alert(err.message));
                    }}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <ClarificationsSection
          accessToken={accessToken}
          productId={Number(id)}
          versionId={Number(versionId)}
        />

        <AnalysisSection
          accessToken={accessToken}
          productId={Number(id)}
          versionId={Number(versionId)}
          contentHash={detail.content_hash}
          claimCount={claims.length}
        />

        <IPScreeningSection
          accessToken={accessToken}
          productId={Number(id)}
          versionId={Number(versionId)}
        />

        <DisclosuresSection
          accessToken={accessToken}
          productId={Number(id)}
          versionId={Number(versionId)}
        />

        <ReportsSection
          accessToken={accessToken}
          productId={Number(id)}
          versionId={Number(versionId)}
        />
      </div>
    </div>
  );
}

// ---- Clarifying questions (interactive classification loop) -----------------

function ClarificationsSection({ accessToken, productId, versionId }) {
  const toast = useToast();
  const [questions, setQuestions] = useState([]);
  const [answered, setAnswered] = useState(0);
  const [drafts, setDrafts] = useState({});
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await api.clarificationQuestions(accessToken, productId, versionId);
      setQuestions(res.data?.questions || []);
      setAnswered(res.data?.answered || 0);
    } catch { setQuestions([]); }
  }, [accessToken, productId, versionId]);

  useEffect(() => { load(); }, [load]);

  const submit = async (key) => {
    const text = (drafts[key] || "").trim();
    if (!text) { setError("Write an answer before recording it."); return; }
    setBusy(key); setError(null);
    try {
      await api.answerClarification(accessToken, productId, versionId, {
        question_key: key, answer: text,
      });
      setDrafts((d) => ({ ...d, [key]: "" }));
      toast("Answer recorded (passport content unchanged)");
      await load();
    } catch (err) { setError(err.message); } finally { setBusy(null); }
  };

  if (questions.length === 0) return null;

  return (
    <Section title={`Clarifying questions (${answered}/${questions.length} answered)`}>
      <p className="muted" style={{ marginTop: 0 }}>
        The minimum questions needed to classify this formulation. Answering records
        an advisory note — record the facts themselves in the passport editors above,
        then re-run analysis.
      </p>
      <ul className="list">
        {questions.map((q) => (
          <li key={q.question_key} className="list-item" style={{ alignItems: "flex-start" }}>
            <div className="item-body">
              <strong>{q.question_text}</strong>
              <div className="badge-row">
                <Badge text={q.answered ? "answered" : "open"} />
                <Badge text={`record in: ${q.destination?.section || "passport"}`} />
              </div>
              {q.destination?.hint && <p className="muted">{q.destination.hint}</p>}
              {q.answered && q.answer && (
                <p><em>Recorded answer:</em> {q.answer}</p>
              )}
              <div style={{ display: "flex", gap: "8px", marginTop: "6px" }}>
                <input
                  placeholder={q.answered ? "Update the recorded answer…" : "Type your answer…"}
                  value={drafts[q.question_key] || ""}
                  onChange={(e) => setDrafts((d) => ({ ...d, [q.question_key]: e.target.value }))}
                  style={{ flex: 1, minWidth: "200px" }}
                />
                <Button variant="small" disabled={busy === q.question_key} onClick={() => submit(q.question_key)}>
                  {busy === q.question_key ? "Saving…" : q.answered ? "Update" : "Record"}
                </Button>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {error && <FormError message={error} />}
    </Section>
  );
}

// ---- Analysis (Phase 5) ----------------------------------------------------

const ANALYSIS_TYPE_LABELS = {
  claim_analysis: "Claim analysis",
  comprehensive: "Comprehensive analysis",
  ip_route_map: "IP route map",
  patent_screening: "Patent screening",
  biodiversity_screening: "Biodiversity/ABS screening",
  tk_screening: "Traditional-knowledge screening",
  product_classification: "Product classification",
  public_disclosure_review: "Public-disclosure review",
};

function AnalysisSection({ accessToken, productId, versionId, contentHash, claimCount }) {
  const [analyses, setAnalyses] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.analyses(accessToken, productId, versionId);
      const items = res.data || [];
      setAnalyses(items);
      setSelected((prev) => (prev ? items.find((a) => a.id === prev.id) || items[0] || null : items[0] || null));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoaded(true);
    }
  }, [accessToken, productId, versionId]);

  useEffect(() => {
    load();
  }, [load]);

  // An analysis run is a real model call: show progress, and if the AI is
  // unavailable the API answers 503 and records a failed run, which we reload.
  const run = async (fn) => {
    setError("");
    setLoading(true);
    try {
      const res = await fn();
      const created = res.data;
      setAnalyses((prev) => [created, ...prev]);
      setSelected(created);
    } catch (err) {
      setError(err.message);
      await load();
    } finally {
      setLoading(false);
    }
  };

  const result = selected?.results;
  const isComprehensive = result?.kind === "comprehensive_analysis";
  const claimReview = isComprehensive ? result.claim_review : result;

  // Spec item 1: every run is pinned to the content hash it analysed. If the
  // version changed afterwards the recorded result is stale and must say so -
  // the UI never presents an old run as the current answer.
  const isStale =
    Boolean(selected?.content_hash) &&
    Boolean(contentHash) &&
    selected.content_hash !== contentHash;

  return (
    <Section title="Analysis" badge={analyses.length}>
      <p className="muted">
        An analysis is advisory. It records a new result against version <strong>content_hash {contentHash?.slice(0, 12)}…</strong> and
        never edits your claims, evidence or ingredients.
      </p>

      <div className="analysis-toolbar">
        <Button
          disabled={loading || claimCount === 0}
          onClick={() => run(() => api.analyzeClaims(accessToken, productId, versionId))}
        >
          {loading ? "Running…" : "Analyze claims"}
        </Button>
        <Button
          variant="ghost"
          disabled={loading}
          onClick={() => run(() => api.analyzeProduct(accessToken, productId, versionId))}
        >
          {loading ? "Running…" : "Full analysis (classification + claims)"}
        </Button>
      </div>

      {claimCount === 0 && (
        <p className="muted">Add at least one claim to run a claim analysis.</p>
      )}

      {loading && (
        <div className="notice notice-info">
          Running the analysis. This calls the AI model and can take a while.
        </div>
      )}
      {error && <p className="form-error">{error}</p>}

      {!loaded ? (
        <Loading />
      ) : analyses.length === 0 ? (
        <Empty message="No analyses recorded for this version yet." />
      ) : (
        <>
          <div className="field">
            <label htmlFor="analysis-run">Recorded runs (newest first)</label>
            <select
              id="analysis-run"
              value={selected?.id ?? ""}
              onChange={(e) =>
                setSelected(analyses.find((a) => a.id === Number(e.target.value)) || null)
              }
            >
              {analyses.map((a) => (
                <option key={a.id} value={a.id}>
                  #{a.id} · {ANALYSIS_TYPE_LABELS[a.analysis_type] || a.analysis_type} · {a.status}
                  {a.created_at ? ` · ${new Date(a.created_at).toLocaleString()}` : ""}
                </option>
              ))}
            </select>
          </div>

          {selected && (
            <div className="analysis-result">
              <div className="badge-row">
                <Badge text={selected.analysis_type} />
                <Badge text={selected.status} />
                {isStale && <Badge text="stale run - newer content exists" />}
                {selected.flags?.map((f) => (
                  <Badge key={f} text={f} />
                ))}
              </div>

              {isStale && (
                <div className="notice notice-warn">
                  This run is out of date: it was recorded for content hash{" "}
                  <strong>{selected.content_hash?.slice(0, 12)}…</strong>, and the
                  version now has <strong>{contentHash?.slice(0, 12)}…</strong>{" "}
                  (claims, ingredients, formulation or markets changed after this
                  run). Re-run the analysis to reflect the latest content.
                </div>
              )}

              {isComprehensive && result.analysis_summary && (
                <AnalysisSummaryCard summary={result.analysis_summary} />
              )}

              {selected.summary && <p className="assessment-text">{selected.summary}</p>}

              {isComprehensive && (
                <ComprehensiveExtras result={result} />
              )}

              {claimReview && (claimReview.claim_status || claimReview.explanation) && (
                <div className="badge-row">
                  {claimReview.claim_status && (
                    <Badge text={claimReview.claim_status} />
                  )}
                </div>
              )}

              {claimReview?.explanation && (
                <WhyThisResult explanation={claimReview.explanation} />
              )}

              {claimReview?.assessments?.length ? (
                <>
                  <h3 className="subheading">Claim assessments ({claimReview.assessments.length})</h3>
                  {claimReview.assessments.map((a) => (
                    <ClaimAssessmentCard key={a.claim_id} assessment={a} />
                  ))}
                </>
              ) : claimReview?.claim_status === "NO_CLAIMS_RECORDED" ? (
                <Empty message="NO_CLAIMS_RECORDED - no claims are recorded on this product version." />
              ) : (
                <Empty message="This run recorded no claim assessments." />
              )}

              {selected.recommendations?.length > 0 && (
                <>
                  <h3 className="subheading">Recommendations</h3>
                  <ul className="missing-list">
                    {selected.recommendations.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </>
              )}

              {selected.warnings?.length > 0 && (
                <>
                  <h3 className="subheading">Warnings &amp; disclaimers</h3>
                  {selected.warnings.map((w, i) => (
                    <div key={i} className="notice notice-warn">
                      {w}
                    </div>
                  ))}
                </>
              )}
            </div>
          )}
        </>
      )}
    </Section>
  );
}

// A "Why this result?" expandable: signal -> why -> missing -> limit.
// Deterministic text supplied by the backend; never a new conclusion here.
function WhyThisResult({ explanation }) {
  if (!explanation) return null;
  return (
    <details className="why-this-result">
      <summary>Why this result?</summary>
      {explanation.signal && <p className="assessment-text">{explanation.signal}</p>}
      {explanation.why && <p className="assessment-rationale">{explanation.why}</p>}
      {explanation.missing?.length > 0 && (
        <>
          <p className="muted">What is still missing:</p>
          <ul className="missing-list">
            {explanation.missing.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </>
      )}
      {explanation.limit && <div className="notice">{explanation.limit}</div>}
    </details>
  );
}

// Spec item 8: a compact analysis-summary card at the top of every full run,
// so the seven key facts are visible without scrolling through sections.
function AnalysisSummaryCard({ summary: s }) {
  if (!s) return null;
  const rows = [
    ["Product version", s.product_version],
    ["Overall status", s.overall_status],
    ["Evidence completeness", s.evidence_completeness],
    ["Claim review", s.claim_review],
    ["Patent screening", s.patent_screening],
    ["Biodiversity screening", s.biodiversity_screening],
    ["Classification", s.classification],
    ["Expert review", s.expert_review],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  return (
    <div className="analysis-summary-card">
      <h3 className="subheading">Analysis summary</h3>
      <table className="feature-table">
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              <td>{String(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClaimAssessmentCard({ assessment: a }) {
  return (
    <div className="assessment">
      <p className="assessment-text">{a.claim_text}</p>
      <div className="badge-row">
        {a.claim_type && <Badge text={a.claim_type} />}
        <Badge text={`declared: ${a.current_evidence_status}`} />
        <Badge text={`AI suggests: ${a.suggested_evidence_status}`} />
        <Badge text={`risk: ${a.risk_level}`} />
        <Badge text={a.review_status} />
        <Badge text={a.provenance} />
        {a.claim_provenance && <Badge text={`provenance: ${a.claim_provenance}`} />}
        {a.evidence_status && <Badge text={`evidence: ${a.evidence_status}`} />}
        {a.independent_verification && (
          <Badge text={`independent: ${a.independent_verification}`} />
        )}
        {a.review_required && <Badge text="review required" />}
      </div>

      {a.reason && <p className="assessment-rationale">{a.reason}</p>}

      {a.expert_verified_locked && (
        <div className="notice notice-locked">
          {a.rationale}
        </div>
      )}
      {a.rationale && !a.expert_verified_locked && (
        <p className="assessment-rationale">{a.rationale}</p>
      )}

      {a.missing_evidence?.length > 0 && (
        <>
          <p className="muted">Missing evidence:</p>
          <ul className="missing-list">
            {a.missing_evidence.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </>
      )}

      {a.citations?.length > 0 && (
        <>
          <p className="muted">Sources ({a.citations.length})</p>
          {a.citations.map((c, i) => (
            <div key={i} className="citation">
              <div>
                [{i + 1}] {c.title} {c.jurisdiction && `(${c.jurisdiction})`} - {" "}
                <span style={{ textTransform: "capitalize" }}>{c.source_type}</span>
              </div>
              {c.relevant_text && <blockquote>{c.relevant_text}</blockquote>}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function ComprehensiveExtras({ result }) {
  const c = result.product_classification;
  return (
    <>
      {c && (
        <>
          <h3 className="subheading">Preliminary classification</h3>
          <div className="badge-row">
            <Badge text={c.status || "UNRESOLVED"} />
            {/* Never headline a category while the status is UNRESOLVED
                (spec item 4): the candidate stays a candidate. */}
            {c.status !== "UNRESOLVED" && <Badge text={c.category} />}
            <Badge text={`confidence: ${c.confidence}`} />
            <Badge text="preliminary" />
            {c.review_required && <Badge text="review required" />}
          </div>
          {c.status === "UNRESOLVED" && (
            <div className="notice notice-warn">
              <strong>Status: UNRESOLVED.</strong> The product category is not
              established yet, so no category (including{" "}
              <em>possible_medicinal_product</em>) is presented as the
              conclusion. Reassess once the missing information below is
              recorded.
              {c.possible_categories?.length > 0 && (
                <>
                  {" "}
                  Possible categories (candidates only):{" "}
                  {c.possible_categories.join(", ")}.
                </>
              )}
            </div>
          )}
          {c.rationale && <p className="assessment-rationale">{c.rationale}</p>}
          {c.status === "UNRESOLVED" && c.missing_information?.length > 0 && (
            <>
              <p className="muted">Missing information for this classification:</p>
              <ul className="missing-list">
                {c.missing_information.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            </>
          )}
          {c.alternative_categories?.length > 0 && (
            <p className="muted">Other plausible categories: {c.alternative_categories.join(", ")}</p>
          )}
        </>
      )}

      {result.market_considerations?.length > 0 && (
        <>
          <h3 className="subheading">Target-market considerations</h3>
          {result.market_considerations.map((m, i) => (
            <div key={i} className="assessment">
              <p className="assessment-text">
                {m.country}
                {m.region ? ` / ${m.region}` : ""}
              </p>
              <p className="assessment-rationale">{m.consideration}</p>
              {m.review_questions?.length > 0 && (
                <ul className="missing-list">
                  {m.review_questions.map((q, j) => (
                    <li key={j}>{q}</li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </>
      )}

      {result.ip_route_map && <RouteMapView routeMap={result.ip_route_map} />}

      {result.patent_signals && (
        <PatentRecordsView result={result.patent_signals} title="Patent signals" />
      )}

      {result.biodiversity_screening && (
        <ScreeningView result={result.biodiversity_screening} title="Biodiversity / ABS" />
      )}

      {result.traditional_knowledge_screening && (
        <ScreeningView
          result={result.traditional_knowledge_screening}
          title="Traditional knowledge"
        />
      )}

      {result.missing_information?.length > 0 && (
        <>
          <h3 className="subheading">Missing information</h3>
          <ul className="missing-list">
            {result.missing_information.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </>
      )}

      {result.deferred_components?.length > 0 && (
        <div className="notice notice-info">
          Not performed by this run (later phases): {result.deferred_components.join("; ")}.
        </div>
      )}
    </>
  );
}

// ---- IP screening (Phase 6) ------------------------------------------------

// A similarity band -> the badge we show. The backend already sends a careful
// label; this only picks a colour, never a stronger claim.
function bandBadgeClass(band) {
  if (band === "high") return "notice notice-warn";
  if (band === "medium") return "notice notice-info";
  return "notice";
}

function RouteMapView({ routeMap }) {
  if (!routeMap?.routes?.length) return null;
  return (
    <>
      <h3 className="subheading">IP route map</h3>
      <div className="badge-row">
        <Badge text="preliminary" />
        <Badge text="review-oriented" />
      </div>
      {routeMap.routes.map((route) => (
        <div key={route.route} className="assessment">
          <p className="assessment-text">
            {route.route_label} - <strong>{route.label}</strong>
          </p>
          {/* Spec item 5: evidence-based, explicit fields for every route. */}
          {route.why_flagged && (
            <p className="assessment-rationale">
              <strong>Why flagged:</strong> {route.why_flagged}
            </p>
          )}
          {route.missing_information?.length > 0 && (
            <>
              <p className="muted">Missing information for this route:</p>
              <ul className="missing-list">
                {route.missing_information.map((m, i) => (
                  <li key={i}>{m}</li>
                ))}
              </ul>
            </>
          )}
          {route.next_action && (
            <p className="assessment-rationale">
              <strong>Next action:</strong> {route.next_action}
            </p>
          )}
          {route.limitation && (
            <div className="notice">Limitation: {route.limitation}</div>
          )}
          <p className="assessment-rationale">{route.rationale}</p>
          {route.signals?.length > 0 && (
            <p className="muted">Signals: {route.signals.join("; ")}</p>
          )}
          {route.review_questions?.length > 0 && (
            <ul className="missing-list">
              {route.review_questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
      {routeMap.missing_information?.length > 0 && (
        <>
          <p className="muted">Missing information affecting the route map:</p>
          <ul className="missing-list">
            {routeMap.missing_information.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function PatentRecordsView({ result, title = "Patent screening" }) {
  if (!result) return null;
  const isDemo = result.records?.some((r) => r.is_demo);
  return (
    <>
      <h3 className="subheading">{title}</h3>
      <div className="badge-row">
        <Badge text={`records: ${result.record_count ?? result.records?.length ?? 0}`} />
        <Badge text={`similarity: ${result.similarity_indicator || "none"}`} />
        {result.retrieval_mode && <Badge text={result.retrieval_mode} />}
        {/* Spec item 6: the response states the corpus facts explicitly. */}
        {result.corpus_type && <Badge text={`corpus: ${result.corpus_type}`} />}
        <Badge
          text={
            result.live_search_performed
              ? "live search performed"
              : "no live search performed"
          }
        />
        <Badge
          text={result.records_verified ? "records verified" : "records not verified"}
        />
        {isDemo && <Badge text="DEMO DATA - not a live search" />}
      </div>

      {result.explanation && <WhyThisResult explanation={result.explanation} />}

      {result.technical_features?.length > 0 && (
        <p className="muted">
          Technical features extracted:{" "}
          {result.technical_features.map((f) => `${f.feature_type}=${f.value}`).join("; ")}
        </p>
      )}

      {result.matching_features?.length > 0 && (
        <>
          <p className="muted">Matching features</p>
          <ul className="missing-list">
            {result.matching_features.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </>
      )}
      {result.different_features?.length > 0 && (
        <>
          <p className="muted">Different features</p>
          <ul className="missing-list">
            {result.different_features.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </>
      )}
      {result.unknown_features?.length > 0 && (
        <>
          <p className="muted">Unknown features (not recorded for this version)</p>
          <ul className="missing-list">
            {result.unknown_features.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </>
      )}

      {result.records?.length === 0 ? (
        <Empty message="No candidate record overlapped with this version." />
      ) : (
        result.records?.map((record) => (
          <div key={record.id || record.record_id} className="assessment">
            {/* Spec item 6: every record carries its verification banner. */}
            {record.record_label && (
              <div
                className={
                  record.verification_status === "VERIFIED_PUBLIC_RECORD"
                    ? "notice notice-info"
                    : "notice notice-warn"
                }
              >
                {record.record_label}
              </div>
            )}
            <p className="assessment-text">{record.title}</p>
            <div className="badge-row">
              <Badge text={record.record_id} />
              <Badge text={record.relevance_label} />
              <Badge
                text={`similarity ${record.similarity} (${record.similarity_band})`}
              />
              <Badge
                text={record.verification_status || (record.is_demo ? "DEMO RECORD" : "record")}
              />
              {record.jurisdiction && <Badge text={record.jurisdiction} />}
            </div>
            {record.publication_date && (
              <p className="muted">Published: {record.publication_date}</p>
            )}
            {record.abstract && <p className="assessment-rationale">{record.abstract}</p>}

            {record.features?.length > 0 && (
              <table className="feature-table">
                <thead>
                  <tr>
                    <th>Feature</th>
                    <th>Record</th>
                    <th>This version</th>
                    <th>Verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {record.features.map((f, i) => (
                    <tr key={i}>
                      <td>{f.feature_type}</td>
                      <td>{f.patent_value}</td>
                      <td>{f.user_value || "-"}</td>
                      <td>{f.verdict}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {record.source_passage && (
              <blockquote>{record.source_passage}</blockquote>
            )}
            {record.uncertainty && (
              <p className="muted">Uncertainty: {record.uncertainty}</p>
            )}
          </div>
        ))
      )}
    </>
  );
}

function ScreeningView({ result, title }) {
  if (!result) return null;
  const statusClass =
    result.status === "REVIEW_RECOMMENDED"
      ? "notice notice-warn"
      : result.status === "NO_IMMEDIATE_CONSIDERATION_IDENTIFIED"
      ? "notice notice-info"
      : "notice";
  return (
    <>
      <h3 className="subheading">{title}</h3>
      <div className={statusClass}>
        Status: <strong>{result.status_label || result.status}</strong>
      </div>

      {result.explanation && <WhyThisResult explanation={result.explanation} />}

      {result.potential_considerations?.length > 0 && (
        <ul className="missing-list">
          {result.potential_considerations.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}

      {result.missing_information?.length > 0 && (
        <>
          <p className="muted">Missing information</p>
          <ul className="missing-list">
            {result.missing_information.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </>
      )}

      {result.review_questions?.length > 0 && (
        <>
          <p className="muted">Review questions</p>
          <ul className="missing-list">
            {result.review_questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </>
      )}

      {result.sources?.length > 0 && (
        <>
          <p className="muted">Sources considered ({result.sources.length})</p>
          {result.sources.map((s, i) => (
            <div key={i} className="citation">
              <div>
                {s.title} - <span style={{ textTransform: "capitalize" }}>{s.source_type}</span>{" "}
                {/* Spec item 7: explicit metadata instead of an ambiguous
                    "AVAILABLE IN {jurisdiction}" concatenation. */}
                <Badge
                  text={
                    s.access_status ||
                    (s.availability === "restricted"
                      ? "RESTRICTED_NOT_ACCESSED"
                      : "PUBLIC")
                  }
                />
                {s.jurisdiction && <Badge text={s.jurisdiction} />}
                {s.verification_status && <Badge text={s.verification_status} />}
              </div>
              <p className="muted">
                {[
                  s.authority ? `Authority: ${s.authority}` : null,
                  `Source type: ${s.source_type}`,
                  s.source_url || s.url
                    ? `URL: ${s.source_url || s.url}`
                    : null,
                  s.retrieved_at ? `Retrieved: ${s.retrieved_at}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              {s.note && <p className="muted">{s.note}</p>}
            </div>
          ))}
        </>
      )}
    </>
  );
}

function IPScreeningSection({ accessToken, productId, versionId }) {
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const [routeMap, setRouteMap] = useState(null);
  const [patents, setPatents] = useState(null);
  const [biodiversity, setBiodiversity] = useState(null);
  const [tk, setTk] = useState(null);
  const [tkSources, setTkSources] = useState(null);
  const [withSources, setWithSources] = useState(false);

  const run = async (label, fn, setter) => {
    setError("");
    setLoading(label);
    try {
      const res = await fn();
      setter(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading("");
    }
  };

  const busy = (label) => loading === label;

  return (
    <Section title="IP screening">
      <p className="muted">
        All of these are preliminary screenings. They identify things worth reviewing - they
        do not determine patentability, legal requirements or government approval, and patent
        screening runs against a labelled demonstration corpus, not a live database.
      </p>

      {error && <p className="form-error">{error}</p>}

      <div className="analysis-toolbar">
        <Button
          disabled={!!loading}
          onClick={() => run("routes", () => api.ipRoutes(accessToken, productId, versionId), setRouteMap)}
        >
          {busy("routes") ? "Loading…" : "IP route map"}
        </Button>
        <Button
          variant="ghost"
          disabled={!!loading}
          onClick={() =>
            run("patents", () => api.patentSearch(accessToken, productId, versionId), (data) =>
              setPatents(data.results)
            )
          }
        >
          {busy("patents") ? "Screening…" : "Screen for patents"}
        </Button>
        <Button
          variant="ghost"
          disabled={!!loading}
          onClick={() =>
            run(
              "bio",
              () => api.biodiversityScreen(accessToken, productId, versionId, withSources),
              (data) => setBiodiversity(data.results)
            )
          }
        >
          {busy("bio") ? "Screening…" : "Biodiversity/ABS screen"}
        </Button>
        <Button
          variant="ghost"
          disabled={!!loading}
          onClick={() =>
            run(
              "tk",
              () => api.tkScreen(accessToken, productId, versionId, withSources),
              (data) => setTk(data.results)
            )
          }
        >
          {busy("tk") ? "Screening…" : "Traditional-knowledge screen"}
        </Button>
        <Button
          variant="ghost"
          disabled={!!loading}
          onClick={() => run("sources", () => api.tkSources(accessToken), setTkSources)}
        >
          {busy("sources") ? "Loading…" : "TK sources"}
        </Button>
      </div>

      <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <input
          type="checkbox"
          checked={withSources}
          onChange={(e) => setWithSources(e.target.checked)}
        />
        Include corpus sources (slower; searches the knowledge base and may download the
        embedding model on a cold machine)
      </label>

      {loading && (
        <div className="notice notice-info">
          Running the screening. A screening may search the corpus for supporting sources.
        </div>
      )}

      {routeMap && <RouteMapView routeMap={routeMap} />}

      {patents && (
        <>
          <PatentRecordsView result={patents} />
          <div className="analysis-toolbar">
            <Button
              variant="ghost"
              disabled={!!loading || !patents.records?.length}
              onClick={() =>
                run(
                  "compare",
                  () => api.patentCompare(accessToken, productId, versionId),
                  () => setLoading("")
                )
              }
            >
              Re-run comparison
            </Button>
          </div>
          {patents.warnings?.map((w, i) => (
            <div key={i} className="notice notice-warn">
              {w}
            </div>
          ))}
        </>
      )}

      {biodiversity && <ScreeningView result={biodiversity} title="Biodiversity / ABS" />}
      {tk && <ScreeningView result={tk} title="Traditional knowledge" />}

      {tkSources && (
        <>
          <h3 className="subheading">Traditional-knowledge sources</h3>
          <p className="muted">{tkSources.restricted_note}</p>
          {tkSources.sources.map((s) => (
            <div key={s.source_id} className="citation">
              <div>
                {s.title} - <span style={{ textTransform: "capitalize" }}>{s.kind}</span>{" "}
                {s.availability === "restricted" ? (
                  <Badge text="RESTRICTED - not accessed" />
                ) : (
                  <Badge text="available" />
                )}
              </div>
              <p className="muted">{s.description}</p>
            </div>
          ))}
        </>
      )}
    </Section>
  );
}

function Section({ title, badge, children }) {
  return (
    <section className="section">
      <h2 className="section-title">
        {title} {badge != null ? <Badge text={String(badge)} /> : null}
      </h2>
      {children}
    </section>
  );
}

function AddIngredientForm({ accessToken, productId, versionId, setIngredients }) {
  const toast = useToast();
  const [form, setForm] = useState({
    common_name: "",
    botanical_name: "",
    sanskrit_name: "",
    plant_part: "",
    quantity: "",
    quantity_unit: "",
    source_type: "",
    source_location: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const field = (name, parse = (v) => v) => (e) =>
    setForm((f) => ({ ...f, [name]: parse(e.target.value) }));

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.createIngredient(
        accessToken,
        productId,
        versionId,
        {
          ...form,
          quantity: form.quantity ? Number(form.quantity) : null,
          source_type: form.source_type || null,
        }
      );
      setIngredients((prev) => [...prev, data.data]);
      toast("Ingredient added successfully");
      setForm({
        common_name: "",
        botanical_name: "",
        sanskrit_name: "",
        plant_part: "",
        quantity: "",
        quantity_unit: "",
        source_type: "",
        source_location: "",
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="inline-form" onSubmit={submit}>
      <input
        className="input"
        placeholder="Common name"
        value={form.common_name}
        onChange={field("common_name")}
        required
      />
      <input
        className="input"
        placeholder="Botanical name"
        value={form.botanical_name}
        onChange={field("botanical_name")}
      />
      <input
        className="input"
        placeholder="Sanskrit name"
        value={form.sanskrit_name}
        onChange={field("sanskrit_name")}
      />
      <input
        className="input"
        placeholder="Plant part"
        value={form.plant_part}
        onChange={field("plant_part")}
      />
      <input
        className="input number"
        placeholder="Quantity"
        value={form.quantity}
        onChange={field("quantity", Number)}
      />
      <input
        className="input"
        placeholder="Unit"
        value={form.quantity_unit}
        onChange={field("quantity_unit")}
      />
      <select
        value={form.source_type}
        onChange={field("source_type")}
      >
        <option value="">(none)</option>
        <option value="cultivated">cultivated</option>
        <option value="wild">wild</option>
      </select>
      <input
        className="input"
        placeholder="Location"
        value={form.source_location}
        onChange={field("source_location")}
      />
      <FormError message={error} />
      <Button disabled={loading} type="submit" variant="small">
        {loading ? "Adding…" : "Add"}
      </Button>
    </form>
  );
}

// Formulation editor: seeds itself from the saved row so a save never blanks
// untouched fields (the API applies every field the request contains).
const FORMULATION_FIELDS = [
  "process_description", "extraction_method", "solvent", "temperature",
  "temperature_unit", "pressure", "pressure_unit", "duration",
  "duration_unit", "concentration", "other_parameters",
];

function UpsertFormulationForm({ accessToken, productId, versionId, formulation, setFormulation }) {
  const toast = useToast();
  const [values, setValues] = useState(() => {
    const src = formulation || {};
    const seed = {
      process_description: "",
      extraction_method: "",
      solvent: "",
      temperature: "",
      temperature_unit: "C",
      pressure: "",
      pressure_unit: "",
      duration: "",
      duration_unit: "",
      concentration: "",
      other_parameters: "",
    };
    for (const key of FORMULATION_FIELDS) {
      if (src[key] != null) seed[key] = String(src[key]);
    }
    return seed;
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const field = (name) => (e) =>
    setValues((f) => ({ ...f, [name]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      // Spec item 3: an empty input means "not provided" - send null, never
      // an empty string, so the backend records the field as absent.
      const payload = { ...values };
      for (const key of FORMULATION_FIELDS) {
        if (payload[key] === "") payload[key] = null;
      }
      payload.temperature = values.temperature ? Number(values.temperature) : null;
      payload.pressure = values.pressure ? Number(values.pressure) : null;
      payload.duration = values.duration ? Number(values.duration) : null;
      payload.concentration = values.concentration ? Number(values.concentration) : null;
      const data = await api.upsertFormulation(
        accessToken,
        productId,
        versionId,
        payload
      );
      setFormulation(data.data);
      toast("Formulation saved successfully");
      // The editor keeps what was just saved; the summary below reflects it too.
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="inline-form" onSubmit={submit}>
      <textarea
        className="input textarea"
        placeholder="Process description"
        aria-label="Process description"
        value={values.process_description}
        onChange={field("process_description")}
      />
      <input
        className="input"
        placeholder="Extraction method"
        aria-label="Extraction method"
        value={values.extraction_method}
        onChange={field("extraction_method")}
      />
      <input
        className="input"
        placeholder="Solvent"
        aria-label="Solvent"
        value={values.solvent}
        onChange={field("solvent")}
      />
      <input
        className="input number"
        placeholder="Temperature"
        aria-label="Temperature"
        value={values.temperature}
        onChange={field("temperature")}
      />
      <input
        className="input"
        placeholder="Temperature unit"
        aria-label="Temperature unit"
        value={values.temperature_unit ?? ""}
        onChange={field("temperature_unit")}
      />
      <input
        className="input"
        placeholder="Pressure"
        aria-label="Pressure"
        value={values.pressure}
        onChange={field("pressure")}
      />
      <input
        className="input number"
        placeholder="Duration"
        aria-label="Duration"
        value={values.duration}
        onChange={field("duration")}
      />
      <input
        className="input"
        placeholder="Concentration"
        aria-label="Concentration"
        value={values.concentration}
        onChange={field("concentration")}
      />
      <input
        className="input"
        placeholder="Other parameters"
        aria-label="Other parameters"
        value={values.other_parameters}
        onChange={field("other_parameters")}
      />
      <FormError message={error} />
      <Button disabled={loading} type="submit" variant="small">
        {loading ? "Saving…" : "Save formulation"}
      </Button>
    </form>
  );
}

function AddClaimForm({ accessToken, productId, versionId, setClaims }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [claim_type, setClaimType] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.createClaim(accessToken, productId, versionId, {
        claim_text: text.trim(),
        claim_type: claim_type || null,
      });
      setClaims((prev) => [...prev, data.data]);
      toast("Claim added successfully");
      setText("");
      setClaimType("");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="inline-form" onSubmit={submit}>
      <textarea
        className="input textarea"
        placeholder="Claim text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        required
      />
      <select
        value={claim_type}
        onChange={(e) => setClaimType(e.target.value)}
      >
        <option value="">(none)</option>
        <option>wellness</option>
        <option>therapeutic</option>
        <option>nutritional</option>
        <option>cosmetic</option>
        <option>structure_function</option>
        <option>traditional_use</option>
      </select>
      <FormError message={error} />
      <Button disabled={loading} type="submit" variant="small">
        {loading ? "Adding…" : "Add claim"}
      </Button>
    </form>
  );
}

function AddEvidenceForm({ accessToken, productId, versionId, setEvidence }) {
  const toast = useToast();
  const [form, setForm] = useState({
    title: "",
    evidence_type: "",
    doi: "",
    publication_date: "",
    language: "",
    authors: "",
    source_url: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const field = (name) => (e) =>
    setForm((f) => ({ ...f, [name]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.createEvidence(
        accessToken,
        productId,
        versionId,
        {
          ...form,
          publication_date: form.publication_date || null,
          evidence_type: form.evidence_type || null,
          doi: form.doi || null,
          language: form.language || null,
          authors: form.authors || null,
          source_url: form.source_url || null,
        }
      );
      setEvidence((prev) => [...prev, data.data]);
      toast("Evidence attached successfully");
      setForm({ title: "", evidence_type: "", doi: "", publication_date: "", language: "", authors: "", source_url: "" });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="inline-form" onSubmit={submit}>
      <input
        className="input"
        placeholder="Evidence title"
        value={form.title}
        onChange={field("title")}
        required
      />
      <select
        value={form.evidence_type}
        onChange={field("evidence_type")}
      >
        <option value="">(none)</option>
        <option>scientific_paper</option>
        <option>clinical_trial</option>
        <option>traditional_text</option>
        <option>pharmacopoeia</option>
        <option>regulatory_document</option>
        <option>other</option>
      </select>
      <input
        className="input"
        placeholder="DOI"
        value={form.doi}
        onChange={field("doi")}
      />
      <input
        className="input"
        placeholder="Publication date (YYYY-MM-DD)"
        value={form.publication_date}
        onChange={field("publication_date")}
      />
      <input
        className="input"
        placeholder="Language"
        value={form.language}
        onChange={field("language")}
      />
      <input
        className="input"
        placeholder="Authors"
        value={form.authors}
        onChange={field("authors")}
      />
      <FormError message={error} />
      <Button disabled={loading} type="submit" variant="small">
        {loading ? "Adding…" : "Attach evidence"}
      </Button>
    </form>
  );
}

function AddTargetMarketForm({ accessToken, productId, versionId, setTargetMarkets }) {
  const toast = useToast();
  const [form, setForm] = useState({
    country: "",
    region: "",
    regulatory_status: "",
    notes: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const field = (name) => (e) =>
    setForm((f) => ({ ...f, [name]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.createTargetMarket(
        accessToken,
        productId,
        versionId,
        {
          country: form.country.trim(),
          region: form.region || null,
          regulatory_status: form.regulatory_status || null,
          notes: form.notes || null,
        }
      );
      setTargetMarkets((prev) => [...prev, data.data]);
      toast("Target market added successfully");
      setForm({ country: "", region: "", regulatory_status: "", notes: "" });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <form className="inline-form" onSubmit={submit}>
      <input
        className="input"
        placeholder="Country"
        value={form.country}
        onChange={field("country")}
        required
      />
      <input
        className="input"
        placeholder="Region"
        value={form.region}
        onChange={field("region")}
      />
      <input
        className="input"
        placeholder="Regulatory status"
        value={form.regulatory_status}
        onChange={field("regulatory_status")}
      />
      <FormError message={error} />
      <Button disabled={loading} type="submit" variant="small">
        {loading ? "Adding…" : "Add market"}
      </Button>
    </form>
  );
}

// ==========================================================================
// Phases 8-10: Disclosures, Reports, Reviews
// ==========================================================================

const DISCLOSURE_TYPES = [
  "conference_presentation", "publication", "website", "investor_disclosure",
  "advertising", "commercial_launch", "other",
];

function DisclosuresSection({ accessToken, productId, versionId }) {
  const toast = useToast();
  const [events, setEvents] = useState([]);
  const [review, setReview] = useState(null);
  const [form, setForm] = useState({ disclosure_type: "conference_presentation", description: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await api.disclosures(accessToken, productId, versionId);
      setEvents(res.data || []);
    } catch { setEvents([]); }
  }, [accessToken, productId, versionId]);

  useEffect(() => { load(); }, [load]);

  const record = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api.createDisclosure(accessToken, productId, versionId, form);
      setForm({ disclosure_type: "conference_presentation", description: "" });
      toast("Disclosure event recorded successfully");
      await load();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  const runReview = async () => {
    setBusy(true); setError(null);
    try {
      const res = await api.disclosureReview(accessToken, productId, versionId);
      setReview(res.data);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return (
    <Section title="Public disclosures">
      <ul>
        {events.map((d) => (
          <li key={d.id}>{d.disclosure_type}: {d.description} <span className="muted">(hash {d.record_hash?.slice(0, 12)}...)</span></li>
        ))}
        {events.length === 0 && <li className="muted">No disclosure events recorded.</li>}
      </ul>
      <form onSubmit={record} style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginTop: "8px" }}>
        <select value={form.disclosure_type} onChange={(e) => setForm({ ...form, disclosure_type: e.target.value })}>
          {DISCLOSURE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <input placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} style={{ flex: 1, minWidth: "200px" }} />
        <Button disabled={busy} type="submit" variant="small">{busy ? "Saving..." : "Record event"}</Button>
      </form>
      <div style={{ marginTop: "8px" }}>
        <Button disabled={busy} onClick={runReview} variant="small" type="button">Run disclosure review</Button>
      </div>
      {error && <FormError message={error} />}
      {review && (
        <div style={{ marginTop: "8px" }}>
          <p><strong>{review.review_status}</strong> ({review.event_count} event(s))</p>
          <ul>{(review.considerations || []).map((c, i) => <li key={i}>{c}</li>)}</ul>
          <ul>{(review.review_questions || []).map((q, i) => <li key={i}><em>{q}</em></li>)}</ul>
        </div>
      )}
    </Section>
  );
}

function ReportsSection({ accessToken, productId, versionId }) {
  const toast = useToast();
  const [reports, setReports] = useState([]);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await api.reports(accessToken, productId, versionId);
      setReports(res.data || []);
    } catch { setReports([]); }
  }, [accessToken, productId, versionId]);

  useEffect(() => { load(); }, [load]);

  const generate = async (kind) => {
    setBusy(kind); setError(null);
    try {
      await api.genReport(accessToken, productId, versionId, kind);
      toast("Report generated successfully");
      await load();
    } catch (err) { setError(err.message); } finally { setBusy(null); }
  };

  const download = async (id) => {
    try {
      const blob = await api.downloadReport(accessToken, id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `report-${id}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch (err) { setError(err.message); }
  };

  return (
    <Section title="Reports">
      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
        {[["ip-brief", "IP brief"], ["disclosure", "Disclosure record"], ["expert-handoff", "Expert handoff"]].map(([kind, label]) => (
          <Button key={kind} disabled={busy !== null} onClick={() => generate(kind)} variant="small" type="button">
            {busy === kind ? "Generating..." : label}
          </Button>
        ))}
      </div>
      {error && <FormError message={error} />}
      <ul style={{ marginTop: "8px" }}>
        {reports.map((r) => (
          <li key={r.id}>
            {r.report_type} (hash {r.content_hash?.slice(0, 12)}...)
            <button className="btn btn-small btn-ghost" onClick={() => download(r.id)} type="button">Download PDF</button>
          </li>
        ))}
        {reports.length === 0 && <li className="muted">No reports generated yet.</li>}
      </ul>
    </Section>
  );
}

function Reviews() {
  const { accessToken } = useAuth();
  const toast = useToast();
  const [reviews, setReviews] = useState([]);
  const [selected, setSelected] = useState(null);
  const [products, setProducts] = useState([]);
  const [versions, setVersions] = useState([]);
  const [form, setForm] = useState({ product_id: "", product_version_id: "", title: "", notes: "" });
  const [sent, setSent] = useState(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState(null);
  const [mailResult, setMailResult] = useState(null);
  const [mailing, setMailing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.reviews(accessToken);
      setReviews(res.data || []);
    } catch { setReviews([]); }
  }, [accessToken]);

  useEffect(() => {
    load();
    (async () => {
      try { setProducts((await api.products(accessToken)).data || []); } catch { setProducts([]); }
    })();
  }, [load, accessToken]);

  // Versions belong to the selected product: offer them by version number so
  // the caller never has to guess a database id (a bare "1" 404s).
  // The render-guard below (not an effect) also resyncs when the selected
  // product arrives without going through the picker, e.g. state preserved
  // across a hot reload.
  const [versionsFor, setVersionsFor] = useState(null);
  const loadVersions = (pid) => {
    if (!pid) { setVersions([]); return; }
    api.versions(accessToken, pid).then(
      (res) => setVersions(res.data || []),
      () => setVersions([])
    );
  };
  if (form.product_id && versionsFor !== form.product_id) {
    setVersionsFor(form.product_id);
    loadVersions(form.product_id);
  }
  const pickProduct = (pid) => {
    setForm({ product_id: pid, product_version_id: "", title: form.title });
    setVersionsFor(pid || null);
    loadVersions(pid);
  };

  const open = async (id) => {
    try { setSelected((await api.reviewDetail(accessToken, id)).data); setMailResult(null); }
    catch (err) { setError(err.message); }
  };

  const act = async (action, body = {}) => {
    if (!selected) return;
    setError(null);
    try {
      setSelected((await api.reviewAction(accessToken, selected.id, action, body)).data);
      toast("Review updated successfully");
      await load();
    } catch (err) { setError(err.message); }
  };

  const notify = async () => {
    if (!selected || mailing) return;
    setError(null); setMailResult(null); setMailing(true);
    try {
      const res = await api.notifyReview(accessToken, selected.id);
      const mail = res.data?.email_notification || null;
      setMailResult(mail);
      if (mail?.sent) {
        toast("Notification email sent to the review desk");
      } else {
        setError(`Email not sent${mail?.reason ? ` (${mail.reason})` : ""} — configure SMTP in the backend .env to enable email notifications.`);
      }
    } catch (err) { setError(err.message); }
    finally { setMailing(false); }
  };

  const create = async (e) => {
    e.preventDefault(); setError(null); setSent(null);
    try {
      const created = await api.createReview(accessToken, {
        product_id: Number(form.product_id),
        product_version_id: Number(form.product_version_id),
        title: form.title || undefined,
        notes: form.notes || undefined,
      });
      // One click genuinely asks for human review: advance the new DRAFT
      // through AI screening to REVIEW_REQUIRED. Every step is audit-logged;
      // if a step fails, the reached state is shown honestly instead.
      let review = created.data;
      const mail = created.data?.email_notification || null;
      try {
        review = (await api.reviewAction(accessToken, review.id, "submit", {})).data;
        review = (await api.reviewAction(accessToken, review.id, "request-review", {})).data;
        review = { ...review, email_notification: mail };
      } catch (advErr) {
        setError(`Review recorded, but auto-advance stopped at ${review?.status || "DRAFT"}: ${advErr.message}`);
      }
      setSent(review);
      toast("Review sent - waiting for human review");
      setForm({ product_id: "", product_version_id: "", title: "", notes: "" });
      setVersions([]); setVersionsFor(null);
      await load();
    } catch (err) { setError(err.message); }
  };

  return (
    <div className="page-stack">
      <Card title="Request a review">
        {error && <FormError message={error} />}
        {sent && (
          <div className="notice" style={{ marginBottom: "12px" }}>
            <strong>Review sent — waiting for human review.</strong>{" "}
            Review #{sent.id}{sent.title ? ` “${sent.title}”` : ""} is now{" "}
            <strong>{sent.status}</strong>.{" "}
            {sent.email_notification?.sent ? (
              <span>A notification email with the request details has been sent to the review desk.</span>
            ) : (
              <span>
                The review-desk email could not be sent
                {sent.email_notification?.reason ? ` (${sent.email_notification.reason})` : ""} —{" "}
                the request itself is recorded and waiting; configure SMTP in the backend
                `.env` to enable email notifications.
              </span>
            )}
          </div>
        )}
        <form onSubmit={create} className="rv-form">
          <div className="field">
            <label>Product</label>
            <select value={form.product_id} onChange={(e) => pickProduct(e.target.value)}>
              <option value="">Select a product…</option>
              {products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Product version</label>
            <select
              value={form.product_version_id}
              onChange={(e) => setForm({ ...form, product_version_id: e.target.value })}
              disabled={!form.product_id}
            >
              <option value="">{form.product_id ? "Select a version…" : "Select a product first…"}</option>
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  Version {v.version_number ?? v.id}
                  {v.content_hash ? ` (${String(v.content_hash).slice(0, 8)}…)` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Title (optional)</label>
            <input placeholder="Review title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </div>
          <div className="field">
            <Button type="submit">Request review</Button>
          </div>
          <div className="field" style={{ gridColumn: "1 / -1" }}>
            <label>What should the reviewer look at? (optional)</label>
            <input
              placeholder="e.g. Please check whether my cold-press claim is substantiated…"
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </div>
        </form>
        <h3 className="subheading" style={{ marginTop: "22px" }}>Your reviews</h3>
        {reviews.length === 0 ? (
          <Empty message="No reviews yet." />
        ) : (
          <ul className="session-list">
            {reviews.map((r) => (
              <li key={r.id}>
                <button className="row-item row-click" onClick={() => open(r.id)} type="button">
                  <span className="row-id">#{r.id}</span>
                  <Badge text={r.status} />
                  <span className="row-meta">Product {r.product_id} · Version {r.product_version_id}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {selected && (
        <Card title={`Review #${selected.id} · ${prettify(selected.status)}`}>
          <p className="muted" style={{ margin: "-6px 0 14px" }}>
            {selected.title || "Untitled"} · {selected.ai_screen_summary || "Not yet screened"}
          </p>
          {(selected.comments || []).length > 0 && (
            <div style={{ marginBottom: "12px" }}>
              {(selected.comments || []).map((c) => (
                <div className="rv-comment" key={c.id}>
                  <b>{prettify(c.author_id)}</b> — {c.body}
                </div>
              ))}
            </div>
          )}
          <div className="rv-comment-row">
            <input
              className="input-line"
              placeholder="Add a comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
            <Button variant="small" type="button" onClick={() => { act("comment", { body: comment }); setComment(""); }}>Comment</Button>
          </div>
          <div className="rv-actions">
            {[["submit", "Submit"], ["request-review", "Request review"], ["request-correction", "Request correction"], ["resubmit", "Resubmit"], ["complete", "Complete"], ["archive", "Archive"]].map(([a, label]) => (
              <Button key={a} variant="small" type="button" onClick={() => act(a)}>{label}</Button>
            ))}
            <Button variant="small" type="button" onClick={notify} disabled={mailing}>
              {mailing ? "Emailing…" : "Email reviewer"}
            </Button>
          </div>
          {mailResult && (
            <p className="muted" style={{ marginTop: "8px", fontSize: "13px" }}>
              {mailResult.sent
                ? "Notification email with the request details has been sent to the review desk."
                : `The review-desk email could not be sent${mailResult.reason ? ` (${mailResult.reason})` : ""}.`}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}

// ==========================================================================
// Overall Product View (spec item 16)
//
// One page for ONE selected Product Passport version. Every section renders
// the stored aggregate from GET .../versions/{id}/overview - the same data
// the chatbot receives - so the page and the assistant can never present two
// different interpretations of the product. Nothing here is simulated:
// statuses come from the API's closed vocabularies, missing values render
// exactly as reported ("Not provided" / "Not recorded"), and switching
// versions clears the page before the newly selected data arrives.
// ==========================================================================

const OV_CSS = `
  .ov { width: 100%; text-align: left; font-family: "Times New Roman", Times, serif; color: #1C2420; }
  .ov h1, .ov h2, .ov h3, .ov h4, .ov p, .ov dl, .ov dd { margin: 0; }
  .ov-title-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
  .ov-title-row .pg-h1 { margin-bottom: 0; }
  .ov-meta { display: flex; flex-wrap: wrap; gap: 8px 14px; margin-top: 14px; align-items: center; }
  .ov-meta-item { font-size: 12.5px; color: #5B6670; }
  .ov-meta-item b { color: #1C2420; font-size: 14px; }
  .ov-hash { font-family: "Times New Roman", Times, serif; font-size: 12px; color: #6B5E43; background: #F3ECDC; border: 1px solid #E7DFCE; border-radius: 7px; padding: 4px 10px; cursor: help; max-width: 100%; overflow-wrap: anywhere; }
  .ov-switch { display: inline-flex; align-items: center; gap: 8px; margin-top: 14px; font-size: 13px; font-weight: 600; color: #6B5E43; }
  .ov-switch select { padding: 9px 12px; border: 1px solid #E4DACA; border-radius: 8px; background: #FFFDF8; color: #1C2420; font-size: 14px; }
  .ov-switch select:focus { outline: 2px solid #1E3A2F; outline-offset: 1px; }
  .ov-notices { border: 1px dashed #E4DACA; background: #FAF7EF; border-radius: 10px; padding: 14px 16px; margin: 6px 0 16px; }
  .ov-notices p { font-size: 13px; line-height: 1.6; color: #5B6670; }
  .ov-notices p + p { margin-top: 8px; }
  .ov-sec { margin-bottom: 16px; }
  .ov-sec-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
  .ov-sec-title { font-size: 13px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: #6B5E43; }
  .ov-sec-sub { font-size: 12.5px; color: #6B7280; margin-top: 4px; }
  .ov-provs { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .ov-prov { font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; background: #EEF2EF; color: #3E5248; border: 1px solid #D8E0DA; border-radius: 999px; padding: 3px 9px; cursor: help; }
  .ov-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px 20px; }
  .ov-f { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .ov-fl { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #6B5E43; margin-top: 12px; }
  .ov-fv { font-size: 14.5px; color: #1C2420; white-space: pre-wrap; overflow-wrap: anywhere; }
  .ov-fv.ov-missing { color: #8A6A14; font-style: italic; }
  .ov-chip { display: inline-flex; align-items: center; font-size: 10.5px; font-weight: 700; letter-spacing: 0.05em; border-radius: 999px; padding: 4px 10px; border: 1px solid #D8E0DA; background: #F3F6F3; color: #3E5248; white-space: nowrap; }
  .ov-chip.ok { background: #E8F3EC; border-color: #BFDCC9; color: #1E5B39; }
  .ov-chip.warn { background: #FBF2DE; border-color: #EBD9AC; color: #7A5A12; }
  .ov-chip.bad { background: #FBECEC; border-color: #EBC9C9; color: #8C2F2F; }
  .ov-chip.muted { background: #F2F1ED; border-color: #E1DED4; color: #6B7280; }
  .ov-chips { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
  .ov-exact { font-size: 13.5px; line-height: 1.6; color: #1C2420; background: #FAF5EC; border-left: 3px solid #B98A2F; padding: 10px 12px; border-radius: 0 8px 8px 0; margin-top: 10px; }
  .ov-alert { background: #FBF2DE; border: 1px solid #EBD9AC; border-radius: 10px; padding: 14px 16px; margin-top: 14px; display: flex; flex-direction: column; gap: 10px; align-items: flex-start; }
  .ov-alert p { font-size: 14px; line-height: 1.6; color: #5C470F; }
  .ov-status-top { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; align-items: flex-start; }
  .ov-status-name { font-family: "Times New Roman", Times, serif; font-weight: 400; font-size: clamp(22px, 2.4vw, 30px); line-height: 1.2; color: #1C2420; margin-top: 6px; overflow-wrap: anywhere; }
  .ov-status-reason { font-size: 14.5px; line-height: 1.65; color: #3F4A44; margin-top: 12px; }
  .ov-status-side { display: flex; gap: 8px; flex-wrap: wrap; }
  .ov-status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 16px; padding-top: 14px; border-top: 1px solid #F0EAD9; }
  .ov-status-grid span { display: block; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #6B5E43; }
  .ov-status-grid b { display: block; font-size: 13.5px; font-weight: 600; color: #1C2420; margin-top: 3px; overflow-wrap: anywhere; }
  .ov-block { border-top: 1px solid #F0EAD9; margin-top: 16px; padding-top: 6px; }
  .ov-ing, .ov-claim, .ov-rec, .ov-run, .ov-act, .ov-sub { background: #FFFDF8; border: 1px solid #E7DFCE; border-radius: 10px; padding: 16px; margin-bottom: 12px; }
  .ov-ing-head, .ov-claim-head, .ov-rec-head, .ov-run-head, .ov-act-head, .ov-sub-head { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; align-items: center; }
  .ov-ing-head b, .ov-rec-head b, .ov-act-head b { font-size: 15px; color: #1C2420; }
  .ov-claim-text { font-size: 15.5px; line-height: 1.5; color: #1C2420; }
  .ov-dl { display: grid; grid-template-columns: 190px 1fr; gap: 7px 16px; margin-top: 12px; }
  .ov-dl dt { font-size: 11.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: #6B5E43; padding-top: 2px; }
  .ov-dl dd { font-size: 14px; color: #1C2420; white-space: pre-wrap; overflow-wrap: anywhere; }
  .ov-list { margin: 8px 0 0; padding-left: 18px; }
  .ov-list li { font-size: 13.5px; line-height: 1.6; color: #3F4A44; }
  .ov-empty { font-size: 13.5px; color: #6B7280; padding: 4px 0; }
  .ov-error { font-size: 14px; color: #8C2F2F; background: #FBECEC; border: 1px solid #EBC9C9; border-radius: 10px; padding: 14px 16px; }
  .ov-run-ref, .ov-rec-meta { font-size: 12.5px; color: #6B7280; margin-top: 8px; overflow-wrap: anywhere; }
  .ov-run-meta { font-size: 12.5px; color: #5B6670; margin-top: 8px; }
  .ov-feats { margin-top: 12px; border-top: 1px dashed #E4DACA; padding-top: 10px; }
  .ov-feat { display: flex; gap: 8px; align-items: baseline; font-size: 13px; color: #3F4A44; margin-top: 6px; overflow-wrap: anywhere; }
  .ov-link { font-size: 13.5px; font-weight: 700; color: #1E3A2F; text-decoration: underline; }
  .ov-prov-map { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 10px 18px; }
  .ov-prov-row { display: flex; justify-content: space-between; gap: 10px; align-items: center; border-bottom: 1px dotted #E7DFCE; padding: 6px 0; }
  .ov-prov-row .ov-fl { margin-top: 0; }
  .ov-sub-head h4 { font-size: 14px; font-weight: 700; letter-spacing: 0.08em; color: #1C2420; }
  .ov-sub { background: #FAF7EF; }
  .ov-sub p { font-size: 13.5px; line-height: 1.6; color: #3F4A44; margin-top: 8px; }
  .ov-act p { font-size: 13.5px; line-height: 1.6; color: #3F4A44; margin-top: 8px; }
  .ov-run p { font-size: 13.5px; line-height: 1.6; color: #3F4A44; margin-top: 8px; }
  .ov-date { font-size: 12.5px; color: #6B7280; }
  @media (max-width: 760px) { .ov-dl { grid-template-columns: 1fr; } }
`;

const OV_PROV_HELP = {
  USER_PROVIDED: "Recorded by you in the Product Passport.",
  SYSTEM_DERIVED: "Counted by the platform from stored rows.",
  SOURCE_BACKED: "Backed by a verified source recorded on this version.",
  ANALYSIS_DERIVED: "Produced by a recorded analysis run.",
  NOT_PROVIDED: "No value is stored for this field.",
  NOT_VERIFIED: "Not independently verified.",
};

// Closed status vocabularies rendered as chips. Only tone varies - the text
// is always the exact status string returned by the API.
const OV_TONE = {
  COMPLETE_FOR_REVIEW: "ok",
  SUPPORTED_BY_ATTACHED_EVIDENCE: "ok",
  SOURCE_BACKED: "ok",
  VERIFIED_PUBLIC_RECORD: "ok",
  NO_RELEVANT_RECORD_IDENTIFIED: "ok",
  SOURCE_DOCUMENTATION_RECORDED: "ok",
  PARTIALLY_COMPLETE: "warn",
  REVIEW_REQUIRED: "warn",
  ANALYSIS_OUTDATED: "warn",
  EVIDENCE_REVIEW_REQUIRED: "warn",
  POTENTIALLY_RELEVANT: "warn",
  FURTHER_REVIEW_RECOMMENDED: "warn",
  INFORMATION_MISSING: "warn",
  ADDITIONAL_INFORMATION_NEEDED: "warn",
  INSUFFICIENT_INFORMATION: "bad",
  USER_PROVIDED_ONLY: "bad",
  EVIDENCE_MISSING: "bad",
  UNRESOLVED: "bad",
  HIGH: "bad",
  MEDIUM: "warn",
  LOW: "muted",
  ANALYSIS_NOT_RUN: "muted",
  NOT_ASSESSED: "muted",
  SEARCH_NOT_RUN: "muted",
  SEARCH_UNAVAILABLE: "muted",
};
const ovTone = (value) => OV_TONE[value] || "muted";

const ovDate = (iso) =>
  iso
    ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    : "Not recorded";

const ovDateTime = (iso) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Not recorded";

function OvProv({ value }) {
  if (!value) return null;
  return (
    <span className="ov-prov" title={OV_PROV_HELP[value] || value}>
      {String(value).replace(/_/g, " ")}
    </span>
  );
}

function OvChip({ text, tone }) {
  if (text === null || text === undefined || text === "") return null;
  return <span className={"ov-chip" + (tone ? ` ${tone}` : "")}>{String(text)}</span>;
}

function OvField({ item }) {
  const missing =
    item.provenance === "NOT_PROVIDED" ||
    item.value === "Not provided" ||
    item.value === "Not recorded";
  return (
    <div className="ov-f">
      <span className="ov-fl">{item.label}</span>
      <span className={"ov-fv" + (missing ? " ov-missing" : "")}>{String(item.value)}</span>
      <OvProv value={item.provenance} />
    </div>
  );
}

function OvFields({ items }) {
  return (
    <div className="ov-grid">
      {(items || []).map((item) => (
        <OvField key={item.key} item={item} />
      ))}
    </div>
  );
}

function OvBulletList({ items }) {
  if (!items || items.length === 0) return null;
  return (
    <ul className="ov-list">
      {items.map((entry, index) => (
        <li key={index}>{String(entry)}</li>
      ))}
    </ul>
  );
}

function OvSection({ title, subtitle, prov, aside, children }) {
  return (
    <div className="card ov-sec">
      <div className="ov-sec-head">
        <div>
          <h2 className="ov-sec-title">{title}</h2>
          {subtitle && <p className="ov-sec-sub">{subtitle}</p>}
        </div>
        <div className="ov-provs">
          {(prov || []).map((entry) => (
            <OvProv key={entry} value={entry} />
          ))}
          {aside}
        </div>
      </div>
      {children}
    </div>
  );
}

function OvRun({ run, empty }) {
  if (!run) return <p className="ov-empty">{empty || "No analysis run is recorded for this section."}</p>;
  return (
    <div className="ov-run-ref">
      <p>
        Run #{run.run_id} · {run.analysis_type} · {run.status} · {ovDateTime(run.timestamp)}
        {run.content_hash ? ` · hash ${String(run.content_hash).slice(0, 12)}…` : ""}
      </p>
      {run.summary && <p>{run.summary}</p>}
    </div>
  );
}

function OverallProductView() {
  const { accessToken } = useAuth();
  const toast = useToast();
  const { id, versionId } = useParams();
  const navigate = useNavigate();

  const [products, setProducts] = useState(null);
  const [listError, setListError] = useState(null);
  const [versionsData, setVersionsData] = useState({ key: null, rows: [] });
  const [data, setData] = useState(null); // last completed load: { key, payload }
  const [failure, setFailure] = useState(null); // last failure: { key, message }
  const [retryToken, setRetryToken] = useState(0);
  const [busy, setBusy] = useState(false);

  const pid = id ? Number(id) : null;
  const vid = versionId ? Number(versionId) : null;
  const currentKey = pid && vid ? `${pid}:${vid}` : null;

  // Version options are keyed to their product, so switching products can
  // never flash the previous product's version list.
  const versions = versionsData.key === pid ? versionsData.rows : [];

  // Product list: drives the default selection and the empty states.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await api.products(accessToken);
        if (alive) setProducts((res && res.data) || []);
      } catch (exc) {
        if (alive) {
          setProducts([]);
          setListError((exc && exc.message) || "Could not load your products.");
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [accessToken]);

  // No parameters in the URL: open the first passport that has a version.
  useEffect(() => {
    if (pid || !products || products.length === 0) return;
    const first = products.find((row) => row.current_version_id);
    if (first) {
      navigate(`/overview/${first.id}/${first.current_version_id}`, { replace: true });
    }
  }, [pid, products, navigate]);

  // Version switcher options for the selected product.
  useEffect(() => {
    if (!pid) return undefined;
    let alive = true;
    (async () => {
      try {
        const res = await api.versions(accessToken, pid);
        if (alive) setVersionsData({ key: pid, rows: (res && res.data) || [] });
      } catch {
        if (alive) setVersionsData({ key: pid, rows: [] });
      }
    })();
    return () => {
      alive = false;
    };
  }, [accessToken, pid]);

  // One load per selected version. The result is stored together with the
  // key it belongs to, so data from another version can never be treated as
  // current: switching versions shows the loading state until the payload
  // for THIS key arrives, and every section is re-fetched from scratch.
  useEffect(() => {
    if (!currentKey) return undefined;
    let alive = true;
    (async () => {
      try {
        const res = await api.productOverview(accessToken, pid, vid);
        const payload = (res && res.data) || null;
        if (payload && payload.product && payload.product.version_id !== vid) {
          throw new Error("The server returned data for a different product version.");
        }
        if (!alive) return;
        setData({ key: currentKey, payload });
        setFailure(null);
      } catch (exc) {
        if (!alive) return;
        setFailure({
          key: currentKey,
          message: (exc && exc.message) || "Could not load the product overview.",
        });
      }
    })();
    return () => {
      alive = false;
    };
  }, [accessToken, pid, vid, currentKey, retryToken]);

  // All view state is derived from the keys above - nothing is cleared
  // synchronously inside an effect, so a version switch can never leave a
  // stale section on screen for even one frame.
  const error =
    currentKey && failure && failure.key === currentKey ? failure.message : null;
  const ready = Boolean(
    currentKey &&
      data &&
      data.key === currentKey &&
      data.payload &&
      data.payload.product &&
      data.payload.product.version_id === vid
  );
  const loading =
    (products === null && !listError) || Boolean(currentKey && !ready && !error);

  const retry = () => {
    setFailure(null);
    setRetryToken((token) => token + 1);
  };

  const rerunAnalysis = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.analyzeProduct(accessToken, pid, vid);
      toast("Analysis recorded for this version.");
      setFailure(null);
      setRetryToken((token) => token + 1);
    } catch (exc) {
      toast((exc && exc.message) || "The analysis could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  const head = (
    <header className="pg-head ov-head">
      <div className="ov-title-row">
        {pid && (
          <Link className="btn btn-ghost" to={`/products/${pid}/versions`}>
            All versions
          </Link>
        )}
      </div>
      {pid &&
        vid &&
        versions.some((row) => row.id === vid) && (
          <label className="ov-switch">
            <span>Version</span>
            <select
              value={vid}
              onChange={(event) => navigate(`/overview/${pid}/${event.target.value}`)}
            >
              {versions.map((row) => (
                <option key={row.id} value={row.id}>
                  Version {row.version_number ?? row.id}
                </option>
              ))}
            </select>
          </label>
        )}
    </header>
  );

  // ---- States before the selected version's data is ready ---------------

  if (loading) {
    return (
      <div className="ov">
        <style>{OV_CSS}</style>
        {head}
        <div className="card">
          <Loading />
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="ov">
        <style>{OV_CSS}</style>
        {head}
        <div className="card">
          {error ? (
            <>
              <p className="ov-error">{error}</p>
              <div className="ov-chips">
                <Button type="button" onClick={() => retry()}>
                  Try again
                </Button>
              </div>
            </>
          ) : listError ? (
            <p className="ov-error">{listError}</p>
          ) : pid && !vid ? (
            <>
              <p className="ov-empty">This product has no version to review yet.</p>
              <Link className="btn" to={`/products/${pid}/versions`}>
                Open versions
              </Link>
            </>
          ) : products && products.length === 0 ? (
            <>
              <p className="ov-empty">
                No Product Passport is available yet. Create a passport first - this
                page reports what a version actually records.
              </p>
              <Link className="btn" to="/products/new">
                + New product
              </Link>
            </>
          ) : (
            <>
              <p className="ov-empty">No product version is selected for review.</p>
              <Link className="btn" to="/products">
                Choose a product
              </Link>
            </>
          )}
        </div>
      </div>
    );
  }

  // ---- Selected version loaded ------------------------------------------

  const o = data.payload;
  const product = o.product;
  const overall = o.overall_status;
  const analysis = o.analysis;
  const rc = o.regulatory_classification;
  const ip = o.ip_review;
  const bio = o.biodiversity_abs_review;
  const tk = o.traditional_knowledge_review;
  const disclosures = o.disclosures;

  return (
    <div className="ov">
      <style>{OV_CSS}</style>
      {head}

      <div className="ov-meta">
        <span className="ov-meta-item">
          <b>{product.name}</b>
        </span>
        <span className="ov-meta-item">Version {product.version}</span>
        <span className="ov-hash" title={product.content_hash || "Not recorded"}>
          Content hash {product.content_hash ? `${product.content_hash.slice(0, 16)}…` : "Not recorded"}
        </span>
        <span className="ov-meta-item">Created {ovDate(product.created_at)}</span>
        <span className="ov-meta-item">
          {product.updated_at
            ? `Updated ${ovDate(product.updated_at)}`
            : product.updated_at_note || "No update timestamp recorded."}
        </span>
        <span className="ov-meta-item">
          Analysis: {analysis.status === "NOT_RUN" ? "not run" : prettify(analysis.status)}
          {analysis.analysis_type ? ` · ${prettify(analysis.analysis_type)}` : ""}
          {analysis.run_id ? ` · run #${analysis.run_id}` : ""}
          {analysis.timestamp ? ` · ${ovDateTime(analysis.timestamp)}` : ""}
        </span>
      </div>

      {/* Spec item 2: the preliminary-decision-support notice is visible on
          the page itself, not buried at the bottom. */}
      <div className="ov-notices" role="note">
        {(o.disclaimers || []).map((text, index) => (
          <p key={index}>{text}</p>
        ))}
      </div>

      {/* ---- Overall status ---- */}
      <div className="card ov-sec">
        <div className="ov-status-top">
          <div>
            <p className="ov-fl" style={{ marginTop: 0 }}>
              Overall status for this version
            </p>
            <h2 className="ov-status-name">{overall.status}</h2>
          </div>
          <div className="ov-status-side">
            <OvChip text={overall.status} tone={ovTone(overall.status)} />
            <OvChip text={`CONFIDENCE ${overall.confidence}`} tone="muted" />
          </div>
        </div>

        <p className="ov-status-reason">{overall.reason}</p>

        {overall.analysis_outdated && (
          <div className="ov-alert">
            <OvChip text="ANALYSIS_OUTDATED" tone={ovTone("ANALYSIS_OUTDATED")} />
            <p>{overall.outdated_notice}</p>
            <Button type="button" onClick={() => rerunAnalysis()} disabled={busy}>
              {busy ? "Re-running…" : "Re-run analysis"}
            </Button>
          </div>
        )}

        {overall.missing_required.length > 0 && (
          <div className="ov-block">
            <p className="ov-fl" style={{ marginTop: 0 }}>
              Missing required information
            </p>
            <OvBulletList items={overall.missing_required} />
          </div>
        )}
        {overall.review_triggers.length > 0 && (
          <div className="ov-block">
            <p className="ov-fl" style={{ marginTop: 0 }}>
              Outstanding review items
            </p>
            <OvBulletList items={overall.review_triggers} />
          </div>
        )}
        {overall.soft_gaps.length > 0 && (
          <div className="ov-block">
            <p className="ov-fl" style={{ marginTop: 0 }}>
              Incomplete details
            </p>
            <OvBulletList items={overall.soft_gaps} />
          </div>
        )}

        <div className="ov-status-grid">
          <div>
            <span>Last completed analysis</span>
            <b>{ovDateTime(overall.last_analysis)}</b>
          </div>
          <div>
            <span>Analysis content hash</span>
            <b title={overall.analysis_version_hash || "Not recorded"}>
              {overall.analysis_version_hash
                ? `${overall.analysis_version_hash.slice(0, 16)}…`
                : "Not recorded"}
            </b>
          </div>
          <div>
            <span>Current version hash</span>
            <b title={overall.current_version_hash || "Not recorded"}>
              {overall.current_version_hash
                ? `${overall.current_version_hash.slice(0, 16)}…`
                : "Not recorded"}
            </b>
          </div>
          <div>
            <span>Completed runs recorded</span>
            <b>{analysis.completed_runs ?? 0}</b>
          </div>
        </div>
      </div>

      {/* ---- 1. Product Facts ---- */}
      <OvSection title="Product Facts" prov={o.provenance.facts}>
        <OvFields items={o.facts.fields} />
      </OvSection>

      {/* ---- 2. Formulation and Process ---- */}
      <OvSection
        title="Formulation and Process"
        prov={o.provenance.formulation}
        aside={
          <Link className="btn btn-small" to={`/products/${pid}/versions/${vid}`}>
            Edit Product Passport
          </Link>
        }
      >
        {!o.formulation.present && (
          <p className="ov-empty">
            No formulation record exists for this version; every field below is
            reported as not provided.
          </p>
        )}
        <OvFields items={o.formulation.fields} />
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Source summary
          </p>
          <OvFields items={o.formulation.source_summary} />
        </div>
      </OvSection>

      {/* ---- 3. Ingredients and Source ---- */}
      <OvSection title="Ingredients and Source" prov={o.provenance.ingredients}>
        {o.ingredients.length === 0 ? (
          <p className="ov-empty">No ingredients are recorded for this version.</p>
        ) : (
          o.ingredients.map((ingredient, index) => (
            <div className="ov-ing" key={ingredient.id ?? index}>
              <div className="ov-ing-head">
                <b>
                  {ingredient.fields.find((f) => f.key === "common_name")?.value ||
                    "Unnamed ingredient"}
                </b>
                <OvProv value={ingredient.provenance} />
              </div>
              <OvFields items={ingredient.fields} />
            </div>
          ))
        )}
      </OvSection>

      {/* ---- 4. Claims and Evidence ---- */}
      <OvSection
        title="Claims and Evidence"
        subtitle="Product evidence and review status."
        prov={o.provenance.claims}
      >
        {o.claims.length === 0 ? (
          <p className="ov-empty">No claims are recorded for this version.</p>
        ) : (
          o.claims.map((claim) => (
            <div className="ov-claim" key={claim.id}>
              <div className="ov-claim-head">
                <p className="ov-claim-text">&ldquo;{claim.claim_text}&rdquo;</p>
                <div className="ov-provs">
                  <OvChip text={claim.evidence_status} tone={ovTone(claim.evidence_status)} />
                  <OvChip text={claim.marketing_status} tone="bad" />
                  <OvChip text={claim.review_status} tone={ovTone(claim.review_status)} />
                </div>
              </div>
              <dl className="ov-dl">
                <dt>Provenance</dt>
                <dd>
                  {claim.provenance} <OvProv value={claim.provenance_label} />
                </dd>
                <dt>Independent verification</dt>
                <dd>{claim.independent_verification}</dd>
                <dt>Reason</dt>
                <dd>{claim.reason || "Not recorded"}</dd>
                <dt>Markets affected</dt>
                <dd>{(claim.markets_affected || []).join(", ") || "Not recorded"}</dd>
                <dt>Evidence linkage</dt>
                <dd>
                  {claim.evidence_linkage}
                  {(claim.linked_evidence || []).length > 0 && (
                    <ul className="ov-list">
                      {claim.linked_evidence.map((doc) => (
                        <li key={doc.id}>
                          {doc.title || "Untitled evidence"} ({doc.verification_status})
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
                <dt>Linked analysis</dt>
                <dd>
                  {claim.linked_analysis
                    ? `${prettify(claim.linked_analysis.analysis_type)} · run #${claim.linked_analysis.run_id} · ${ovDateTime(claim.linked_analysis.timestamp)}`
                    : "No recorded analysis assessment is linked to this claim."}
                </dd>
                <dt>Last updated</dt>
                <dd>{ovDateTime(claim.last_updated)}</dd>
              </dl>
              {claim.warning && (
                <div className="ov-alert">
                  <p>
                    <strong>{claim.marketing_status}.</strong> {claim.warning}
                  </p>
                </div>
              )}
            </div>
          ))
        )}

        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Evidence documents
          </p>
          {o.evidence.length === 0 ? (
            <p className="ov-empty">No evidence documents are attached to this product version.</p>
          ) : (
            o.evidence.map((doc) => (
              <div className="ov-rec" key={doc.id}>
                <div className="ov-rec-head">
                  <b>{doc.title || "Untitled evidence"}</b>
                  <OvChip text={prettify(doc.verification_status)} tone="muted" />
                </div>
                <p className="ov-rec-meta">
                  {prettify(doc.evidence_type)} · {doc.provenance} · recorded {ovDate(doc.created_at)}
                </p>
                {doc.source_url && (
                  <p className="ov-rec-meta">
                    <a href={doc.source_url} target="_blank" rel="noreferrer">
                      {doc.source_url}
                    </a>
                  </p>
                )}
                {doc.doi && <p className="ov-rec-meta">DOI: {doc.doi}</p>}
                {doc.publication_date && (
                  <p className="ov-rec-meta">Published: {doc.publication_date}</p>
                )}
              </div>
            ))
          )}
        </div>
      </OvSection>

      {/* ---- 5. Target Markets ---- */}
      <OvSection
        title="Target Markets"
        subtitle="Market launch review."
        prov={o.provenance.target_markets}
      >
        {o.target_markets.count === 0 ? (
          <p className="ov-empty">No target markets are recorded for this version.</p>
        ) : (
          <>
            <div className="ov-chips">
              {o.target_markets.markets.map((market) => (
                <OvChip key={market.country} text={market.country} tone="muted" />
              ))}
            </div>
            <OvFields
              items={o.target_markets.markets.map((market) => ({
                key: `market-${market.country}`,
                label: `${market.country} · regulatory status`,
                value: market.regulatory_status.value,
                provenance: market.regulatory_status.provenance,
              }))}
            />
            <div className="ov-block">
              <p className="ov-fl" style={{ marginTop: 0 }}>
                Declared market records
              </p>
              <OvBulletList
                items={o.target_markets.markets.map(
                  (market) =>
                    `${market.country} — region: ${market.region}; market-specific evidence: ${market.market_evidence_count} recorded; last market review: ${market.last_review_date}`
                )}
              />
              <p className="ov-rec-meta">{o.target_markets.markets[0].market_evidence_note}</p>
            </div>
            {o.target_markets.sections.map((section) => (
              <div className="ov-sub" key={section.label}>
                <div className="ov-sub-head">
                  <h4>{section.label}</h4>
                  <OvChip text={section.status} tone={ovTone(section.status)} />
                </div>
                {section.consideration && <p>{section.consideration}</p>}
                <p className="ov-exact">{section.evidence_note}</p>
                <p className="ov-fl">Sources used</p>
                {section.sources_used.length === 0 ? (
                  <p className="ov-empty">No market-specific source is recorded for this section.</p>
                ) : (
                  <OvBulletList items={section.sources_used} />
                )}
                <p className="ov-fl">Missing information</p>
                <OvBulletList items={section.missing_information} />
                <p className="ov-fl">Review questions</p>
                <OvBulletList items={section.review_questions} />
                <p>
                  <strong>Next action:</strong> {section.next_action}
                </p>
              </div>
            ))}
          </>
        )}
      </OvSection>

      {/* ---- 6. Regulatory Classification ---- */}
      <OvSection
        title="Regulatory Classification"
        prov={o.provenance.regulatory_classification}
      >
        <div className="ov-chips">
          <OvChip text={rc.status} tone={ovTone(rc.status)} />
          <OvChip text={`CONFIDENCE ${rc.confidence}`} tone={ovTone(rc.confidence)} />
          <OvChip text={rc.review_required ? "REVIEW_REQUIRED" : "NO_REVIEW_REQUIRED"} tone={ovTone(rc.review_required ? "REVIEW_REQUIRED" : "")} />
        </div>
        <dl className="ov-dl">
          <dt>Classification</dt>
          <dd>{rc.classification}</dd>
          <dt>Candidate category</dt>
          <dd>{rc.candidate_category || "Not recorded"}</dd>
          <dt>Reason</dt>
          <dd>{rc.reason}</dd>
          <dt>Review required</dt>
          <dd>{rc.review_required ? "YES" : "NO"}</dd>
          <dt>Source of this result</dt>
          <dd>{rc.source}</dd>
          <dt>Analysis run</dt>
          <dd>
            <OvRun run={rc.analysis_run} empty="No classification analysis is recorded for this version." />
          </dd>
        </dl>
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Candidate pathways (review only)
          </p>
          <OvBulletList items={rc.possible_pathways.map((pathway) => prettify(pathway))} />
          <p className="ov-rec-meta">{rc.possible_pathways_note}</p>
        </div>
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Missing information for classification
          </p>
          <OvBulletList items={rc.missing_information} />
        </div>
      </OvSection>

      {/* ---- 7. IP and Prior-Art Review ---- */}
      <OvSection
        title="IP and Prior-Art Review"
        subtitle="IP and compliance review."
        prov={o.provenance.ip_review}
      >
        <div className="ov-chips">
          <OvChip text={ip.status} tone={ovTone(ip.status)} />
          <OvChip text={ip.provenance} tone={ip.provenance === "SOURCE_BACKED" ? "ok" : "muted"} />
        </div>
        <p className="ov-status-reason">{ip.reason}</p>
        {ip.notice && <p className="ov-exact">{ip.notice}</p>}
        {ip.demo_notice && (
          <div className="ov-alert">
            <p>
              <strong>{ip.demo_notice}</strong>
            </p>
          </div>
        )}
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Screening run
          </p>
          <OvRun run={ip.run} empty="No patent screening has been recorded for this version." />
          {ip.run && (
            <p className="ov-rec-meta">
              Corpus: {ip.run.corpus_type || "DEMO_CORPUS"} · live search performed:{" "}
              {ip.run.live_search_performed ? "yes" : "no"}
            </p>
          )}
          {ip.synthetic_records_omitted > 0 && (
            <p className="ov-rec-meta">
              {ip.synthetic_records_omitted} stored demonstration record(s) were omitted
              from this view: they are labelled demonstration data, not verified public
              records, and are never presented as search results.
            </p>
          )}
        </div>
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Verified public records
          </p>
          {ip.records.length === 0 ? (
            <p className="ov-empty">
              No verified patent record is listed for this version.
            </p>
          ) : (
            ip.records.map((record) => {
              const features = record.features || [];
              const matched = (record.matched_features || []).length;
              const different = (record.different_features || []).length;
              const unknown = (record.unknown_features || []).length;
              return (
                <div className="ov-rec" key={record.record_id || record.id}>
                  <div className="ov-rec-head">
                    <b>{record.title || record.record_id}</b>
                    <OvChip text={record.priority} tone="warn" />
                  </div>
                  <dl className="ov-dl">
                    <dt>Record</dt>
                    <dd>{record.record_id}</dd>
                    <dt>Patent number</dt>
                    <dd>{record.patent_number || "Not recorded"}</dd>
                    <dt>Jurisdiction</dt>
                    <dd>{record.jurisdiction || "Not recorded"}</dd>
                    <dt>Assignee</dt>
                    <dd>{record.assignee || "Not recorded"}</dd>
                    <dt>Verification</dt>
                    <dd>{record.verification_status}</dd>
                    <dt>Relevance</dt>
                    <dd>
                      {record.relevance_label || "Not recorded"}
                      {record.similarity_band ? ` · similarity band ${record.similarity_band}` : ""}
                    </dd>
                    <dt>Retrieved</dt>
                    <dd>{ovDate(record.retrieval_date)}</dd>
                    <dt>Priority date</dt>
                    <dd>{record.priority_date}</dd>
                    <dt>Why included</dt>
                    <dd>{record.why_included}</dd>
                  </dl>
                  {record.source_url && (
                    <p className="ov-rec-meta">
                      <a href={record.source_url} target="_blank" rel="noreferrer">
                        {record.source_url}
                      </a>
                    </p>
                  )}
                  {features.length > 0 && (
                    <div className="ov-feats">
                      <p className="ov-fl" style={{ marginTop: 0 }}>
                        Feature comparison ({matched} matching · {different} differing ·{" "}
                        {unknown} undetermined)
                      </p>
                      {features.map((feature, index) => (
                        <p className="ov-feat" key={index}>
                          <OvChip
                            text={feature.verdict}
                            tone={
                              feature.verdict === "match"
                                ? "ok"
                                : feature.verdict === "different"
                                ? "warn"
                                : "muted"
                            }
                          />
                          <span>
                            {feature.feature_type}: record &ldquo;
                            {feature.patent_value ?? "—"}&rdquo; vs version &ldquo;
                            {feature.user_value ?? "—"}&rdquo;
                          </span>
                        </p>
                      ))}
                    </div>
                  )}
                  <p className="ov-exact">{record.features_disclaimer}</p>
                </div>
              );
            })
          )}
          {ip.features_disclaimer && <p className="ov-exact">{ip.features_disclaimer}</p>}
        </div>
      </OvSection>

      {/* ---- 8. Biodiversity and ABS ---- */}
      <OvSection title="Biodiversity and ABS" prov={o.provenance.biodiversity_abs_review}>
        <div className="ov-chips">
          <OvChip text={bio.status} tone={ovTone(bio.status)} />
          {bio.screening_status && (
            <OvChip text={`SCREENING ${bio.screening_status}`} tone="muted" />
          )}
        </div>
        <p className="ov-status-reason">{bio.reason}</p>
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Considerations from the recorded screening
          </p>
          <OvBulletList items={bio.potential_considerations} />
        </div>
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Missing information
          </p>
          <OvBulletList items={bio.missing_information} />
          <p className="ov-fl">Fields the product record does not hold</p>
          <OvBulletList items={bio.missing_fields} />
        </div>
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Review questions
          </p>
          <OvBulletList items={bio.review_questions} />
          <OvRun run={bio.run} empty="Biodiversity/ABS screening has not been recorded for this version." />
        </div>
        {bio.collected && (bio.collected.origins || []).length > 0 && (
          <div className="ov-block">
            <p className="ov-fl" style={{ marginTop: 0 }}>
              Recorded source origins
            </p>
            <OvBulletList items={bio.collected.origins} />
          </div>
        )}
      </OvSection>

      {/* ---- 9. Traditional-Knowledge ---- */}
      <OvSection
        title="Traditional-Knowledge Review"
        prov={o.provenance.traditional_knowledge_review}
      >
        <div className="ov-chips">
          <OvChip text={tk.status} tone={ovTone(tk.status)} />
        </div>
        <dl className="ov-dl">
          <dt>Traditional use recorded</dt>
          <dd>{tk.traditional_use_recorded}</dd>
          <dt>Source supplied</dt>
          <dd>{tk.source_supplied}</dd>
          <dt>Public source status</dt>
          <dd>{tk.public_source_status}</dd>
          <dt>Restricted source status</dt>
          <dd>{tk.restricted_source_status}</dd>
          <dt>Corpus sources retrieved</dt>
          <dd>{tk.corpus_sources_found ?? "Not recorded"}</dd>
          <dt>Reference sources listed</dt>
          <dd>{tk.registry_sources_listed ?? "Not recorded"}</dd>
        </dl>
        {tk.notice && <p className="ov-exact">{tk.notice}</p>}
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Considerations
          </p>
          <OvBulletList items={tk.potential_considerations} />
          <p className="ov-rec-meta">{tk.reason}</p>
        </div>
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Missing information
          </p>
          <OvBulletList items={tk.missing_information} />
          <p className="ov-fl">Review questions</p>
          <OvBulletList items={tk.review_questions} />
        </div>
        {tk.restricted_sources_excluded && tk.restricted_sources_excluded.length > 0 && (
          <p className="ov-exact">
            Restricted sources excluded from this review:{" "}
            {tk.restricted_sources_excluded.join(", ")}. They were not accessed,
            searched or reproduced.
          </p>
        )}
        {tk.sources_note && <p className="ov-rec-meta">{tk.sources_note}</p>}
        <OvRun run={tk.run} empty="Traditional-knowledge screening has not been recorded for this version." />
      </OvSection>

      {/* ---- 10. Disclosure Review ---- */}
      <OvSection title="Disclosure Review" prov={o.provenance.disclosures}>
        <div className="ov-chips">
          <OvChip text={disclosures.review_status} tone="muted" />
          <OvChip text={`${disclosures.event_count} EVENT(S) RECORDED`} tone="muted" />
        </div>
        {disclosures.notice && <p className="ov-exact">{disclosures.notice}</p>}
        <p className="ov-status-reason">{disclosures.advisory}</p>
        {disclosures.events.length > 0 && (
          <div className="ov-block">
            <p className="ov-fl" style={{ marginTop: 0 }}>
              Recorded disclosure events
            </p>
            {disclosures.events.map((event) => (
              <div className="ov-rec" key={event.id}>
                <div className="ov-rec-head">
                  <b>{prettify(event.disclosure_type)}</b>
                  <span className="ov-date">{event.disclosure_date || ovDate(event.created_at)}</span>
                </div>
                <p className="ov-rec-meta">{event.description || "No description recorded."}</p>
                {event.venue_or_channel && (
                  <p className="ov-rec-meta">Channel: {event.venue_or_channel}</p>
                )}
                <p className="ov-rec-meta">
                  Record hash: {event.record_hash || "Not recorded"} · Verification ID:{" "}
                  {event.verification_id || "Not recorded"}
                </p>
              </div>
            ))}
          </div>
        )}
        <div className="ov-block">
          <p className="ov-fl" style={{ marginTop: 0 }}>
            Considerations
          </p>
          <OvBulletList items={disclosures.considerations} />
          <p className="ov-fl">Review questions</p>
          <OvBulletList items={disclosures.review_questions} />
        </div>
        {(disclosures.warnings || []).length > 0 && (
          <div className="ov-block">
            <p className="ov-fl" style={{ marginTop: 0 }}>
              Warnings
            </p>
            <OvBulletList items={disclosures.warnings} />
          </div>
        )}
        <p className="ov-rec-meta">{disclosures.disclaimer}</p>
      </OvSection>

      {/* ---- 11. Analysis History ---- */}
      <OvSection title="Analysis History" prov={o.provenance.analysis_history}>
        {o.analysis_history.length === 0 ? (
          <p className="ov-empty">No analysis run is recorded for this version.</p>
        ) : (
          o.analysis_history.map((run) => (
            <div className="ov-run" key={run.run_id}>
              <div className="ov-run-head">
                <b>{prettify(run.analysis_type)}</b>
                <div className="ov-provs">
                  <OvChip text={run.status} tone="muted" />
                  {run.outdated && <OvChip text="OUTDATED" tone="bad" />}
                  <span className="ov-date">{ovDateTime(run.timestamp)}</span>
                </div>
              </div>
              {run.outdated && <p className="ov-exact">{run.outdated_notice}</p>}
              <p className="ov-run-meta">
                Run #{run.run_id} · sources used: {run.source_count ?? "Not recorded"} ·
                claims analysed: {run.claims_analysed ?? "Not recorded"} · markets
                considered: {run.markets_analysed ?? "Not recorded"} · missing-information
                items: {run.missing_information_count ?? "Not recorded"} · content hash:{" "}
                {run.hash_matches === true
                  ? "matches the current version"
                  : run.hash_matches === false
                  ? "does not match the current version"
                  : "not recorded for this run"}
              </p>
              {run.summary && <p>{run.summary}</p>}
            </div>
          ))
        )}
      </OvSection>

      {/* ---- 12. Recommended Actions ---- */}
      <OvSection title="Recommended Actions" prov={o.provenance.recommended_actions}>
        {o.recommended_actions.length === 0 ? (
          <p className="ov-empty">
            No outstanding action was derived from the recorded data for this version.
          </p>
        ) : (
          o.recommended_actions.map((action) => (
            <div className="ov-act" key={action.id}>
              <div className="ov-act-head">
                <b>{action.title}</b>
                <div className="ov-provs">
                  <OvChip text={action.priority} tone={ovTone(action.priority)} />
                  <OvChip text={action.status} tone="muted" />
                </div>
              </div>
              <p>{action.reason}</p>
              <p className="ov-rec-meta">Section: {prettify(action.section)}</p>
              <Link className="ov-link" to={action.link}>
                Open →
              </Link>
            </div>
          ))
        )}
      </OvSection>

      {/* ---- Provenance map ---- */}
      <OvSection
        title="Provenance"
        subtitle="Where the values in every section above come from."
      >
        <div className="ov-prov-map">
          {Object.entries(o.provenance || {}).map(([section, values]) => (
            <div className="ov-prov-row" key={section}>
              <span className="ov-fl">{prettify(section)}</span>
              <span className="ov-provs">
                {(values || []).map((entry) => (
                  <OvProv key={entry} value={entry} />
                ))}
              </span>
            </div>
          ))}
        </div>
        {o.missing_information.length > 0 && (
          <div className="ov-block">
            <p className="ov-fl" style={{ marginTop: 0 }}>
              Missing information for this version
            </p>
            <OvBulletList items={o.missing_information} />
          </div>
        )}
      </OvSection>
    </div>
  );
}

// ==========================================================================
// Phase 4: Knowledge Base (Document Upload & Ingestion)
// ==========================================================================

function KnowledgeBase() {
  const { accessToken } = useAuth();
  const toast = useToast();
  const [status, setStatus] = useState(null);
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [myOnly, setMyOnly] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [form, setForm] = useState({
    title: "",
    source_type: "regulation",
    jurisdiction: "India",
    language: "en",
    is_public: false,
  });
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [st, dc] = await Promise.all([
        api.knowledgeStatus(accessToken),
        api.knowledgeDocuments(accessToken, myOnly ? "my_uploads_only=true" : ""),
      ]);
      setStatus(st);
      setDocs(dc);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [accessToken, myOnly]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) {
      setError("Please select a file to upload (.pdf, .txt, .md)");
      return;
    }
    setError(null);
    setSuccess(null);
    setUploading(true);

    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("title", form.title.trim() || file.name);
      fd.append("source_type", form.source_type);
      fd.append("jurisdiction", form.jurisdiction || "");
      fd.append("language", form.language || "en");
      fd.append("is_public", form.is_public ? "true" : "false");

      await api.uploadDocument(accessToken, fd);
      setSuccess("Document uploaded and ingested into RAG corpus successfully!");
      toast("Document uploaded successfully");
      setForm({
        title: "",
        source_type: "regulation",
        jurisdiction: "India",
        language: "en",
        is_public: false,
      });
      setFile(null);
      e.target.reset();
      loadData();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this document and all its indexed chunks?")) return;
    try {
      await api.deleteDocument(accessToken, id);
      setDocs((prev) => prev.filter((d) => d.id !== id));
      toast("Document removed successfully");
      loadData();
    } catch (err) {
      alert("Delete failed: " + err.message);
    }
  };

  const handleReindex = async (id) => {
    try {
      await api.reindexDocument(accessToken, id);
      toast("Document re-indexed successfully");
      loadData();
    } catch (err) {
      alert("Re-index failed: " + err.message);
    }
  };

  return (
    <div className="kb">
      {status && (
        <div className="kb-stats">
          <div className="stat-box">
            <strong>{status.total_documents}</strong> <span>Documents</span>
          </div>
          <div className="stat-box">
            <strong>{status.public_documents}</strong> <span>Public</span>
          </div>
          <div className="stat-box">
            <strong>{status.private_documents}</strong> <span>Private</span>
          </div>
          {status.demo_mode && (
            <div className="stat-box" style={{ background: "#FFF7E0", borderColor: "#EADCA8" }}>
              <strong style={{ color: "#8A6A14" }}>Demo</strong>
              <span>Mode active</span>
            </div>
          )}
        </div>
      )}

      <div style={{ marginTop: "4px" }}>
        <Card title="Upload your own document">
          <p className="muted" style={{ margin: "-8px 0 18px" }}>
            Add your own documents to the corpus so the assistant can cite them.
          </p>
          <form onSubmit={handleUpload}>
            <div className="field">
              <label>Document file</label>
              <label className={"kb-file" + (file ? " has" : "")}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                </svg>
                <span>{file ? file.name : "Choose a file (.pdf, .txt, .md)"}</span>
                <input
                  type="file"
                  accept=".pdf,.txt,.text,.md"
                  onChange={(e) => setFile(e.target.files[0] || null)}
                />
              </label>
            </div>
            <div className="kb-form">
              <div className="field">
                <label>Document title</label>
                <input
                  type="text"
                  placeholder="e.g. Clinical Study on Ashwagandha 2025"
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  required
                />
              </div>
              <div className="field">
                <label>Source type</label>
                <select
                  value={form.source_type}
                  onChange={(e) => setForm({ ...form, source_type: e.target.value })}
                >
                  <option value="regulation">Regulation</option>
                  <option value="patent">Patent</option>
                  <option value="law">Law</option>
                  <option value="official_guidance">Official Guidance</option>
                  <option value="scientific_paper">Scientific Paper</option>
                  <option value="traditional_knowledge">Traditional Knowledge</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div className="field">
                <label>Jurisdiction</label>
                <input
                  type="text"
                  placeholder="e.g. India, WIPO, EU"
                  value={form.jurisdiction}
                  onChange={(e) => setForm({ ...form, jurisdiction: e.target.value })}
                />
              </div>
              <div className="field" style={{ display: "flex", alignItems: "center", paddingTop: "20px" }}>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={form.is_public}
                    onChange={(e) => setForm({ ...form, is_public: e.target.checked })}
                  />
                  Make this document visible to all users (admin only)
                </label>
              </div>
            </div>

            <FormError message={error} />
            <FormSuccess message={success} />

            <div style={{ marginTop: "12px" }}>
              <Button disabled={uploading} type="submit">
                {uploading ? "Uploading & indexing\u2026" : "Upload & index document"}
              </Button>
            </div>
          </form>
        </Card>
      </div>

      <div style={{ marginTop: "24px" }}>
        <Card title="Corpus documents">
          <div className="kb-toolbar">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={myOnly}
                onChange={(e) => setMyOnly(e.target.checked)}
              />
              Show only my uploaded documents
            </label>
            <Button variant="small" onClick={loadData}>Refresh</Button>
          </div>

          {loading ? (
            <Loading />
          ) : docs.length === 0 ? (
            <Empty message="No documents match this filter yet." />
          ) : (
            <ul className="list">
              {docs.map((d) => (
                <li key={d.id} className="list-item" style={{ alignItems: "flex-start" }}>
                  <div className="item-body">
                    <strong>{d.title}</strong>
                    <div className="badge-row">
                      <Badge text={d.source_type} />
                      {d.jurisdiction && <Badge text={d.jurisdiction} />}
                      <Badge text={d.is_public ? "Public" : "Private"} />
                      <span
                        className="badge"
                        style={{
                          backgroundColor:
                            d.status === "INDEXED" ? "#d1e7dd" : d.status === "FAILED" ? "#f8d7da" : "#fff3cd",
                          color:
                            d.status === "INDEXED" ? "#0f5132" : d.status === "FAILED" ? "#842029" : "#664d03",
                        }}
                      >
                        {d.status ? d.status.charAt(0) + d.status.slice(1).toLowerCase() : "Pending"} · {d.chunk_count ?? 0} chunks
                      </span>
                    </div>
                    {d.error_message && (
                      <p className="kb-error">Error: {d.error_message}</p>
                    )}
                    <p className="muted" style={{ margin: "6px 0 0", fontSize: "12.5px" }}>
                      Uploaded {new Date(d.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                    </p>
                  </div>
                  <div className="kb-doc-actions">
                    <Button variant="small" onClick={() => handleReindex(d.id)}>Re-index</Button>
                    <Button variant="danger" onClick={() => handleDelete(d.id)}>Delete</Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div style={{ marginTop: "24px" }}>
        <OfficialSourcesSection accessToken={accessToken} />
      </div>
    </div>
  );
}

// ---- Authoritative sources registry (SIH: free databases directly,
// paid subscriptions only with explicit, logged permission) -----------------

function OfficialSourcesSection({ accessToken }) {
  const toast = useToast();
  const [entries, setEntries] = useState([]);
  const [topics, setTopics] = useState([]);
  const [q, setQ] = useState("");
  const [topic, setTopic] = useState("");
  const [access, setAccess] = useState("");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [handoff, setHandoff] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (topic) params.set("topic", topic);
      if (access) params.set("access", access);
      const qs = params.toString() ? `?${params.toString()}` : "";
      const res = await api.officialSources(accessToken, qs);
      setEntries(res.data?.sources || res.data || []);
    } catch (err) { setError(err.message); }
  }, [accessToken, q, topic, access]);

  useEffect(() => {
    api.officialSourceTopics(accessToken).then(
      (res) => setTopics(res.data?.topics || res.data || [])
    ).catch(() => setTopics([]));
  }, [accessToken]);

  useEffect(() => { load(); }, [load]);

  const grant = async (entry) => {
    if (!window.confirm(
      `Grant this platform permission to hand you off to "${entry.title}"?\n\n` +
      `The permission is logged with a timestamp and can be revoked at any time. ` +
      `The platform never fetches paid data itself.`
    )) return;
    setBusy(entry.id); setError(null); setHandoff(null);
    try {
      await api.grantSourceConsent(accessToken, {
        source_id: entry.id,
        access_type: entry.access || "PAID_SUBSCRIPTION",
        scope: ["handoff"],
        confirm: true,
      });
      toast("Permission granted and logged");
      await load();
    } catch (err) { setError(err.message); } finally { setBusy(null); }
  };

  const openViaPermission = async (entry) => {
    setBusy(entry.id); setError(null); setHandoff(null);
    try {
      const res = await api.requestSourceAccess(accessToken, entry.id);
      setHandoff(res.data);
    } catch (err) { setError(err.message); } finally { setBusy(null); }
  };

  return (
    <Card title="Authoritative sources registry">
      <p className="muted" style={{ margin: "-8px 0 18px" }}>
        Free official databases open directly. Paid or restricted sources need your
        explicit, logged permission first — the platform hands you off and never
        fetches paid data itself.
      </p>
      <div className="kb-toolbar">
        <input
          placeholder="Search registries, statutes, treaties…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{ flex: 1, minWidth: "200px" }}
        />
        <select value={topic} onChange={(e) => setTopic(e.target.value)}>
          <option value="">All topics</option>
          {topics.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={access} onChange={(e) => setAccess(e.target.value)}>
          <option value="">All access types</option>
          <option value="FREE">Free</option>
          <option value="FREE_REGISTRATION">Free registration</option>
          <option value="PAID_SUBSCRIPTION">Paid subscription</option>
          <option value="THIRD_PARTY_API">Third-party API</option>
        </select>
        <Button variant="small" onClick={load}>Search</Button>
      </div>
      {error && <FormError message={error} />}
      <ul className="list" style={{ marginTop: "12px" }}>
        {entries.map((s) => (
          <li key={s.id} className="list-item" style={{ alignItems: "flex-start" }}>
            <div className="item-body">
              <strong>{s.title}</strong>
              <div className="badge-row">
                {s.jurisdiction && <Badge text={s.jurisdiction} />}
                {s.ip_type && <Badge text={String(s.ip_type).replace(/_/g, " ")} />}
                <Badge text={String(s.access || "").replace(/_/g, " ")} />
                {s.requires_permission && <Badge text="permission required" />}
              </div>
              {s.restricted_note && <p className="muted">{s.restricted_note}</p>}
            </div>
            <div className="kb-doc-actions">
              {!s.requires_permission && s.url && (
                <a className="btn btn-small" href={s.url} target="_blank" rel="noreferrer">Open direct</a>
              )}
              {s.requires_permission && (
                <>
                  <Button variant="small" disabled={busy === s.id} onClick={() => grant(s)}>
                    {busy === s.id ? "Saving…" : "Grant permission"}
                  </Button>
                  <Button variant="small" disabled={busy === s.id} onClick={() => openViaPermission(s)}>
                    Open via permission
                  </Button>
                </>
              )}
            </div>
          </li>
        ))}
        {entries.length === 0 && <li className="muted">No registry entries match.</li>}
      </ul>
      {handoff && (
        <div className="notice" style={{ marginTop: "12px" }}>
          <strong>Permission verified — handoff issued.</strong>{" "}
          {handoff.url ? (
            <a href={handoff.url} target="_blank" rel="noreferrer">Open {handoff.source_title || "the source"} yourself</a>
          ) : (
            <span>{handoff.note || "Open the source yourself; access was logged."}</span>
          )}
          <div className="muted">Mode: {handoff.mode || "HANDOFF"} · this access was written to your evidence trail.</div>
        </div>
      )}
    </Card>
  );
}

// ---- Knowledge graph & agent (relational reasoning) ---------------------------

/**
 * Radial SVG visualisation of one graph node and its edges.
 * Clicking a neighbour re-centres the canvas on it. Pure SVG, no library.
 */
function GraphCanvas({ detail, colors, onSelect }) {
  if (!detail || !detail.node) return null;
  const center = detail.node;
  const seen = new Map();
  (detail.edges || []).forEach((e) => {
    [e.from, e.to].forEach((n) => {
      if (n && n.id !== center.id && !seen.has(n.id)) seen.set(n.id, n);
    });
  });
  const neighbours = [...seen.values()].slice(0, 14);
  const W = 640, H = 380, CX = W / 2, CY = H / 2, R = 140;
  const pos = neighbours.map((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(neighbours.length, 1) - Math.PI / 2;
    return { n, x: CX + R * Math.cos(a), y: CY + R * Math.sin(a) };
  });
  const edgeFor = (id) =>
    (detail.edges || []).find(
      (e) => (e.from && e.from.id === id) || (e.to && e.to.id === id)
    );
  const short = (s, n = 22) =>
    s && s.length > n ? s.slice(0, n - 1) + "…" : (s || "");
  return (
    <svg className="gcanvas" viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", background: "#FDFBF4", border: "1px solid #EFE7D5", borderRadius: "12px" }} role="img" aria-label={`Knowledge graph centred on ${center.canonical_name}`}>
      {pos.map(({ n, x, y }) => {
        const e = edgeFor(n.id);
        return (
          <g key={n.id} className="sat">
            <line className="edge-flow" x1={CX} y1={CY} x2={x} y2={y} stroke="#C9BFA6" strokeWidth="1.5" />
            <text x={(CX + x) / 2} y={(CY + y) / 2 - 6} textAnchor="middle" fontSize="9.5" fill="#6B5E43">
              {short(e ? e.relation : "", 18)}
            </text>
          </g>
        );
      })}
      {pos.map(({ n, x, y }) => (
        <g key={"n" + n.id} className="node-g sat" onClick={() => onSelect(n.id)}>
          <circle cx={x} cy={y} r="20" fill={colors[n.node_type] || "#5B6670"} opacity="0.88" />
          <text x={x} y={y + 34} textAnchor="middle" fontSize="10.5" fill="#1C2420">
            {short(n.canonical_name)}
          </text>
        </g>
      ))}
      <circle className="pulse-ring" cx={CX} cy={CY} r="30" fill="none" stroke={colors[center.node_type] || "#1E3A2F"} strokeWidth="2" />
      <circle cx={CX} cy={CY} r="30" fill={colors[center.node_type] || "#1E3A2F"} />
      <text x={CX} y={CY + 48} textAnchor="middle" fontSize="12" fontWeight="700" fill="#1C2420">
        {short(center.canonical_name, 34)}
      </text>
      <text x={CX} y={CY + 62} textAnchor="middle" fontSize="10" fill="#6B5E43">
        {center.node_type} · {detail.edge_count} edge(s)
      </text>
    </svg>
  );
}

const GRAPH_CSS = `
.graph-grid { display: grid; grid-template-columns: minmax(300px, 400px) 1fr; gap: 16px; align-items: start; margin-top: 16px; }
.graph-left { max-height: 600px; overflow-y: auto; padding-right: 4px; }
.graph-right { position: sticky; top: 12px; }
.graph-bottom { margin-top: 16px; }
@media (max-width: 900px) {
  .graph-grid { grid-template-columns: 1fr; }
  .graph-right { position: static; }
  .graph-left { max-height: 320px; }
}
.gcanvas .edge-flow { stroke-dasharray: 6 5; animation: gflow 1.2s linear infinite; }
@keyframes gflow { to { stroke-dashoffset: -11; } }
.gcanvas .pulse-ring { transform-box: fill-box; transform-origin: center; animation: gpulse 2.4s ease-out infinite; }
@keyframes gpulse { 0% { transform: scale(1); opacity: 0.55; } 70% { transform: scale(1.9); opacity: 0; } 100% { transform: scale(1.9); opacity: 0; } }
.gcanvas .sat { animation: gfade 0.45s ease both; }
@keyframes gfade { from { opacity: 0; } to { opacity: 1; } }
.gcanvas .node-g { cursor: pointer; }
.gcanvas .node-g:hover circle { filter: brightness(1.15); }
`;

const GRAPH_NODE_TYPES = ["STATUTE", "RULE", "TREATY", "IP_TYPE",
  "FORMULATION_CATEGORY", "PRODUCT", "INGREDIENT", "BOTANICAL_SPECIES",
  "JURISDICTION", "REGISTRY", "CASE", "OBLIGATION", "REGULATOR",
  "CORPUS_DOCUMENT"];

function GraphPage() {
  const { accessToken } = useAuth();
  const toast = useToast();
  const [stats, setStats] = useState(null);
  const [nodes, setNodes] = useState([]);
  const [q, setQ] = useState("");
  const [nodeType, setNodeType] = useState("");
  const [detail, setDetail] = useState(null);
  const [centerId, setCenterId] = useState(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [path, setPath] = useState(null);
  const [pathMsg, setPathMsg] = useState("");

  const NODE_COLORS = {
    STATUTE: "#1E3A2F", RULE: "#2F6B4F", TREATY: "#3A6EA5",
    IP_TYPE: "#B98A2F", FORMULATION_CATEGORY: "#7A5B00",
    PRODUCT: "#6A3FB5", INGREDIENT: "#2E8B57", BOTANICAL_SPECIES: "#4C9A52",
    JURISDICTION: "#8A2E1F", REGISTRY: "#5B6670", CASE: "#444444",
    OBLIGATION: "#A34A00", REGULATOR: "#005B70", CORPUS_DOCUMENT: "#888888",
  };
  const [agentQ, setAgentQ] = useState("");
  const [run, setRun] = useState(null);
  const [traces, setTraces] = useState([]);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  const searchNodes = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams();
      if (nodeType) params.set("node_type", nodeType);
      if (q.trim()) params.set("q", q.trim());
      const res = await api.graphNodes(accessToken, params.toString() ? `?${params.toString()}` : "");
      const list = res.data?.nodes || [];
      setNodes(list);
      // Centre the visualisation on the first node until the user picks one.
      if (centerId === null && list.length > 0) {
        try {
          const first = await api.graphNodeDetail(accessToken, list[0].id);
          setDetail(first.data);
          setCenterId(list[0].id);
        } catch { /* the list still renders below */ }
      }
    } catch (err) { setError(err.message); }
  }, [accessToken, q, nodeType, centerId]);

  useEffect(() => { searchNodes(); }, [searchNodes]);

  const build = async (full) => {
    setBusy("build"); setError(null);
    try {
      const res = await api.graphBuild(accessToken, full);
      setStats(res.data);
      toast(full ? "Graph rebuilt from scratch" : "Graph refreshed");
      await searchNodes();
    } catch (err) { setError(err.message); } finally { setBusy(null); }
  };

  const openNode = async (id) => {
    setError(null);
    try {
      const res = await api.graphNodeDetail(accessToken, id);
      setDetail(res.data);
      setCenterId(id);
    } catch (err) { setError(err.message); }
  };

  const findPath = async (e) => {
    e.preventDefault();
    setError(null); setPath(null); setPathMsg("");
    try {
      const res = await api.graphPaths(accessToken, from.trim(), to.trim());
      setPath(res.data?.path || null);
      setPathMsg(res.data?.path ? "" : (res.message || "No relational path found between those concepts."));
    } catch (err) { setError(err.message); }
  };

  const runAgent = async (e) => {
    e.preventDefault();
    if (!agentQ.trim()) return;
    setBusy("agent"); setError(null); setRun(null);
    try {
      const res = await api.agentRun(accessToken, { query: agentQ.trim(), max_steps: 5 });
      setRun(res);
      const tr = await api.agentTraces(accessToken);
      setTraces(tr.data?.traces || []);
    } catch (err) { setError(err.message); } finally { setBusy(null); }
  };

  useEffect(() => {
    api.agentTraces(accessToken).then(
      (res) => setTraces(res.data?.traces || [])
    ).catch(() => setTraces([]));
  }, [accessToken]);

  return (
    <div>
      <style>{GRAPH_CSS}</style>
      {error && <FormError message={error} />}

      <Section title="Graph build">
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <Button variant="small" disabled={busy === "build"} onClick={() => build(false)}>
            {busy === "build" ? "Building…" : "Build / refresh"}
          </Button>
          <Button variant="small" disabled={busy === "build"} onClick={() => build(true)}>
            Rebuild from scratch
          </Button>
        </div>
        {stats && (
          <p className="muted">
            {stats.nodes_total} nodes · {stats.edges_total} edges · {stats.duration_ms} ms
          </p>
        )}
      </Section>

      <div className="graph-grid">
        <div className="graph-left">
          <Section title="Browse nodes">
            <div className="kb-toolbar">
              <input placeholder="Search node names…" value={q} onChange={(e) => setQ(e.target.value)} style={{ flex: 1, minWidth: "180px" }} />
              <select value={nodeType} onChange={(e) => setNodeType(e.target.value)}>
                <option value="">All types</option>
                {GRAPH_NODE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <Button variant="small" onClick={searchNodes}>Search</Button>
            </div>
            <ul className="list">
              {nodes.map((n) => (
                <li key={n.id} className="list-item">
                  <div className="item-body">
                    <strong>{n.canonical_name}</strong>
                    <div className="badge-row">
                      <Badge text={n.node_type} />
                      {n.jurisdiction && <Badge text={n.jurisdiction} />}
                    </div>
                  </div>
                  <Button variant="small" onClick={() => openNode(n.id)}>Edges</Button>
                </li>
              ))}
              {nodes.length === 0 && <li className="muted">No nodes match.</li>}
            </ul>
          </Section>
        </div>
        <div className="graph-right">
          <Section title="Knowledge graph">
            {detail ? (
              <>
                <GraphCanvas detail={detail} colors={NODE_COLORS} onSelect={openNode} />
                <p className="muted">Click any neighbour to re-centre the graph on it.</p>
              </>
            ) : (
              <p className="muted">Pick a node on the left to draw its neighbourhood.</p>
            )}
          </Section>
        </div>
      </div>

      <div className="graph-bottom">
      {detail && (
        <Section title={`${detail.node?.canonical_name} — ${detail.edge_count} edge(s)`}>
          <ul className="list">
            {(detail.edges || []).map((e) => (
              <li key={e.id} className="list-item">
                <span>{e.from?.canonical_name || detail.node?.canonical_name} —[{e.relation}]→ {e.to?.canonical_name || detail.node?.canonical_name}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Shortest path">
        <form onSubmit={findPath} style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <input placeholder="From concept or id" value={from} onChange={(e) => setFrom(e.target.value)} style={{ flex: 1, minWidth: "160px" }} />
          <input placeholder="To concept or id" value={to} onChange={(e) => setTo(e.target.value)} style={{ flex: 1, minWidth: "160px" }} />
          <Button variant="small" type="submit">Find path</Button>
        </form>
        {path && (
          <ol style={{ marginTop: "8px" }}>
            {(path.nodes || path || []).map?.((n, i) => (
              <li key={i}>{typeof n === "string" ? n : (n.canonical_name || n.name || JSON.stringify(n))}</li>
            ))}
          </ol>
        )}
        {pathMsg && <p className="muted">{pathMsg}</p>}
      </Section>

      <Section title="Agent run (multi-step, citation-validated)">
        <form onSubmit={runAgent} style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <input
            placeholder="Ask a multi-step IP question…"
            value={agentQ}
            onChange={(e) => setAgentQ(e.target.value)}
            style={{ flex: 1, minWidth: "240px" }}
          />
          <Button variant="small" type="submit" disabled={busy === "agent"}>
            {busy === "agent" ? "Running…" : "Run agent"}
          </Button>
        </form>
        {run && (
          <div style={{ marginTop: "8px" }}>
            <p>{run.answer}</p>
            <div className="badge-row">
              <Badge text={`confidence: ${run.confidence}`} />
              <Badge text={`${run.steps_used}/${run.max_steps} steps`} />
              {run.insufficient_evidence && <Badge text="insufficient evidence" />}
              <Badge text="review required" />
            </div>
            {(run.citations || []).length > 0 && (
              <ul className="list">
                {run.citations.map((c, i) => (
                  <li key={i} className="list-item">
                    [{i + 1}] {c.title} {c.confidence_label && <Badge text={c.confidence_label} />}
                  </li>
                ))}
              </ul>
            )}
            <p className="muted">{run.disclaimer}</p>
          </div>
        )}
      </Section>

      <Section title="Past runs">
        <ul className="list">
          {traces.map((t) => (
            <li key={t.id} className="list-item">
              <span>#{t.id} — {t.query} ({t.steps_used} steps, {t.confidence})</span>
            </li>
          ))}
          {traces.length === 0 && <li className="muted">No agent runs yet.</li>}
        </ul>
      </Section>
      </div>
    </div>
  );
}

// ==========================================================================
// Phase 4: RAG Assistant & Chatbot
// ==========================================================================

/**
 * Market-entry context panel shown above an assistant answer.
 *
 * Renders the four spec blocks (MARKET CONTEXT / SOURCE SCOPE /
 * EVIDENCE STATUS / JURISDICTION WARNING), the market-specific
 * evidence-gap warnings, and a collapsible "Why this answer?" with the
 * selected markets, per-jurisdiction source counts, excluded
 * jurisdictions, missing information and recorded claim reviews.
 */
function ChatMarketPanel({ m }) {
  const hasScope = (m.market_context || []).length > 0 || (m.jurisdiction_filter || []).length > 0;
  if (!hasScope) return null;

  const ev = m.evidence_status;
  const why = m.why_this_answer;
  const gaps = m.evidence_gap_warnings || [];
  const claims = m.claim_reviews || [];
  const statusLabel = ev
    ? ev.overall_status === "INSUFFICIENT"
      ? ev.launch_decision === "CANNOT_BE_DETERMINED"
        ? "Insufficient for launch decision"
        : "Insufficient evidence"
      : ev.overall_status === "PARTIALLY_SUPPORTED"
        ? "Partially supported"
        : "Supported by retrieved sources"
    : null;
  const sourcesUsed = why ? Object.entries(why.sources_used || {}) : [];

  return (
    <div className="market-panel">
      <div className="mp-block">
        <div className="mp-head">MARKET CONTEXT</div>
        <ul>
          {(m.market_context || []).map((label) => (
            <li key={label}>- {label}</li>
          ))}
        </ul>
      </div>

      <div className="mp-block">
        <div className="mp-head">SOURCE SCOPE</div>
        <ul>
          {(m.market_context || []).map((label) => (
            <li key={label}>- {label}-specific sources</li>
          ))}
          <li>
            - Jurisdiction switch:{" "}
            {m.jurisdiction_mode === "india"
              ? "India only"
              : m.jurisdiction_mode === "international"
                ? "International only"
                : "Both (passport markets decide)"}
          </li>
          <li>
            - Private documents:{" "}
            {m.private_search_performed ? "searched" : "not searched"}
          </li>
        </ul>
      </div>

      {ev && (
        <div className="mp-block">
          <div className="mp-head">EVIDENCE STATUS</div>
          <div className="mp-status">{statusLabel}</div>
          {ev.launch_decision && ev.launch_decision !== "NOT_APPLICABLE" && (
            <div className="mp-sub">Launch decision: {ev.launch_decision}</div>
          )}
          {ev.reason && <div className="mp-sub">{ev.reason}</div>}
        </div>
      )}

      {m.jurisdiction_warning && (
        <div className="mp-block mp-warning">
          <div className="mp-head">JURISDICTION WARNING</div>
          <div>{m.jurisdiction_warning}</div>
        </div>
      )}

      {gaps.map((g, i) => (
        <div className="mp-gap" key={i}>{g}</div>
      ))}

      <details className="mp-why">
        <summary>Why this answer?</summary>
        <div className="mp-why-body">
          <div className="mp-why-row">
            <strong>Selected markets:</strong>{" "}
            {why ? (why.selected_markets || []).join(", ") : (m.market_context || []).join(", ")}
          </div>
          <div className="mp-why-row">
            <strong>Sources used:</strong>
            <ul>
              {sourcesUsed.map(([label, count]) => (
                <li key={label}>
                  {label}: {count}
                </li>
              ))}
            </ul>
          </div>
          <div className="mp-why-row">
            <strong>Sources excluded:</strong>
            <ul>
              {why && (why.sources_excluded || []).length > 0 ? (
                (why.sources_excluded || []).map((s) => <li key={s}>{s}</li>)
              ) : (
                <li>None</li>
              )}
            </ul>
          </div>
          <div className="mp-why-row">
            <strong>Missing information:</strong>
            <ul>
              {why && (why.missing_information || []).length > 0 ? (
                (why.missing_information || []).map((s) => <li key={s}>{s}</li>)
              ) : (
                <li>None recorded</li>
              )}
            </ul>
          </div>
          {claims.length > 0 && (
            <div className="mp-why-row">
              <strong>Recorded claims:</strong>
              {claims.map((c, i) => (
                <div className="mp-claim" key={i}>
                  <div className="mp-claim-text">&ldquo;{c.claim_text}&rdquo;</div>
                  <div className="mp-claim-meta">
                    <span className="mp-tag">Provenance: {c.provenance}</span>
                    <span className="mp-tag">Evidence: {c.evidence_status}</span>
                    <span className="mp-tag">
                      Independent verification: {c.independent_verification}
                    </span>
                    <span className="mp-tag mp-tag-review">Marketing use: {c.marketing_use}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </details>
    </div>
  );
}


// Activity statuses shown while the assistant response is being generated.
// EDIT THESE to change the wording. Keep each message honest: the chat flow
// really does (1) read the query, (2) search the verified corpus (pgvector +
// FTS hybrid retrieval), (3) compare/rerank the retrieved passages, (4) draft
// the cited answer. Do NOT name a specific source (e.g. "Checking Charaka
// Samhita…") unless the app actually accessed that source.
const AYURVEDA_ACTIVITY_MESSAGES = [
  "Understanding your query…",
  "Searching the verified corpus…",
  "Comparing relevant information…",
  "Formulating the response…",
];

function AyurvedaActivityIndicator({
  active,
  messages = AYURVEDA_ACTIVITY_MESSAGES,
  intervalMs = 1900,
}) {
  const [index, setIndex] = useState(0);
  // The parent mounts this only while generating (`{loading && <…/>}`), so
  // every request starts from the first status on a fresh mount and unmounts
  // (stopping the timer) when the answer arrives or an error occurs. The
  // interval callback below is the only state update — no sync setState.
  useEffect(() => {
    if (!active || messages.length <= 1) return;
    const id = setInterval(() => {
      setIndex((i) => (i + 1) % messages.length);
    }, intervalMs);
    return () => clearInterval(id);
  }, [active, messages, intervalMs]);
  if (!active) return null;
  return (
    <div className="ai-activity" role="status" aria-live="polite" aria-atomic="true">
      <span className="ai-activity-dot" aria-hidden="true" />
      {/* key restarts the fade/slide animation on every status change */}
      <span className="ai-activity-text" key={index}>
        {messages[index]}
      </span>
    </div>
  );
}

function ChatAssistant() {
  const { accessToken } = useAuth();
  const toast = useToast();
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Optional Product Passport Context
  const [products, setProducts] = useState([]);
  const [selectedProductId, setSelectedProductId] = useState("");
  const [versions, setVersions] = useState([]);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [includeMyDocs, setIncludeMyDocs] = useState(true);
  const [inputLanguage, setInputLanguage] = useState("en");
  const [outputLanguage, setOutputLanguage] = useState("en");
  // Jurisdiction switch (SIH requirement A1: "explicit jurisdiction switch …
  // with the two answer-sets kept visibly separate").
  // "both" = passport-market scope (default); "india" = Indian sources only;
  // "international" = labelled non-Indian sources only. Sent as
  // `jurisdiction_mode` on every chat request.
  const [jurisdictionMode, setJurisdictionMode] = useState("both");

  // Escalation state
  const [escalating, setEscalating] = useState(false);
  const [escalationResult, setEscalationResult] = useState(null);

  // PDF attachments queued for the next message
  const [attachments, setAttachments] = useState([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  // Which LLM answers: "groq" (default) | "sarvam"
  const [llmProvider, setLlmProvider] = useState(() => {
    try {
      return localStorage.getItem("ipsakti_llm_provider") === "sarvam" ? "sarvam" : "groq";
    } catch {
      return "groq";
    }
  });
  // Voice: microphone input + spoken replies
  const [voiceOn, setVoiceOn] = useState(false);
  const [listening, setListening] = useState(false);
  const fileInputRef = useRef(null);
  const recognitionRef = useRef(null);

  // Load sessions & products
  const loadSessions = useCallback(async () => {
    try {
      const data = await api.conversations(accessToken);
      setSessions(data);
    } catch {
      setSessions([]);
    }
  }, [accessToken]);

  useEffect(() => {
    loadSessions();
    (async () => {
      try {
        const prodData = await api.products(accessToken);
        setProducts(prodData.data || []);
      } catch {
        setProducts([]);
      }
    })();
  }, [loadSessions, accessToken]);

  // Load versions when product changes
  useEffect(() => {
    if (!selectedProductId) {
      setVersions([]);
      setSelectedVersionId("");
      return;
    }
    (async () => {
      try {
        const res = await api.versions(accessToken, selectedProductId);
        setVersions(res.data || []);
        if (res.data?.length > 0) {
          setSelectedVersionId(res.data[0].id);
        }
      } catch {
        setVersions([]);
      }
    })();
  }, [selectedProductId, accessToken]);

  // Load active session messages
  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      return;
    }
    (async () => {
      try {
        const res = await api.conversationDetail(accessToken, activeSessionId);
        setMessages(res.messages || []);
      } catch {
        setMessages([]);
      }
    })();
  }, [activeSessionId, accessToken]);

  // ---- Provider toggle (Groq default; choice persists locally) ----
  const chooseProvider = (p) => {
    setLlmProvider(p);
    try {
      localStorage.setItem("ipsakti_llm_provider", p);
    } catch {
      /* storage unavailable - keep in-memory choice */
    }
  };

  // ---- PDF attachment ----
  const handleFileSelect = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files can be attached to a chat message.");
      return;
    }
    setUploadingAttachment(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (activeSessionId) fd.append("session_id", String(activeSessionId));
      const res = await api.uploadChatAttachment(accessToken, fd);
      const att = (res && res.data) || res;
      setAttachments((prev) => [
        ...prev,
        { id: att.id, filename: att.filename, char_count: att.char_count || 0, truncated: !!att.truncated },
      ]);
      if ((att.char_count || 0) === 0) {
        toast(`${att.filename} attached, but no readable text was found in it (scanned image?). The chatbot may not be able to use it.`);
      } else {
        toast(`${att.filename} attached successfully`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setUploadingAttachment(false);
    }
  };

  // ---- Voice: speech-to-text (browser built-in engine) ----
  const SPEECH_LANGS = { en: "en-IN", hi: "hi-IN", bn: "bn-IN" };
  const startListening = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setError("Speech input is not available in this browser - type your message, or try Chrome.");
      return;
    }
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    const rec = new SR();
    rec.lang = SPEECH_LANGS[inputLanguage] || "en-IN";
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = (event) => {
      let transcript = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript;
      }
      setInputMessage(transcript);
    };
    rec.onerror = (event) => {
      setListening(false);
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setError("Microphone access was blocked. Allow the microphone in your browser and try again.");
      } else if (event.error !== "aborted" && event.error !== "no-speech") {
        setError("Speech input could not start - you can type your message instead.");
      }
    };
    rec.onend = () => setListening(false);
    recognitionRef.current = rec;
    setError(null);
    setListening(true);
    try {
      rec.start();
    } catch {
      setListening(false);
    }
  };
  const stopListening = () => {
    try {
      if (recognitionRef.current) recognitionRef.current.stop();
    } catch {
      /* already stopped */
    }
    setListening(false);
  };

  // ---- Voice: text-to-speech replies (browser built-in engine) ----
  const speakReply = (text) => {
    if (!voiceOn || !text) return;
    const synth = window.speechSynthesis;
    if (!synth) return;
    synth.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = SPEECH_LANGS[outputLanguage] || "en-IN";
    const voices = synth.getVoices() || [];
    const exact = voices.find((v) => v.lang && v.lang.replace("_", "-") === utter.lang);
    const loose = voices.find((v) => v.lang && v.lang.replace("_", "-").startsWith(utter.lang.slice(0, 2)));
    if (exact || loose) utter.voice = exact || loose;
    synth.speak(utter);
  };
  const toggleVoice = () => {
    setVoiceOn((v) => {
      if (v && window.speechSynthesis) window.speechSynthesis.cancel();
      return !v;
    });
  };

  const handleSend = async (e) => {
    e?.preventDefault();
    const query = inputMessage.trim();
    if (!query || loading) return;
    // The PDF upload and the chat request are separate calls: sending while
    // the upload is still in flight would submit attachment_ids=[] and the
    // assistant would honestly answer that no PDF was provided. Block Send
    // until the upload finishes (the button is disabled too; this is the
    // keyboard/edge-case guard).
    if (uploadingAttachment) {
      setError("Your PDF is still uploading — please wait a few seconds and send again once it shows as attached.");
      return;
    }

    setError(null);
    setInputMessage("");
    setLoading(true);

    // Optimistically show user message
    const tempUserMsg = {
      id: Date.now(),
      role: "user",
      content: query,
      citations: [],
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    try {
      const payload = {
        message: query,
        session_id: activeSessionId || null,
        product_id: selectedProductId ? parseInt(selectedProductId) : null,
        product_version_id: selectedVersionId ? parseInt(selectedVersionId) : null,
        include_my_documents: includeMyDocs,
        input_language: inputLanguage,
        output_language: outputLanguage,
        attachment_ids: attachments.map((a) => a.id),
        provider: llmProvider,
        jurisdiction_mode: jurisdictionMode,
      };

      const res = await api.chat(accessToken, payload);

      if (!activeSessionId) {
        setActiveSessionId(res.session_id);
        loadSessions();
      }

      const assistantMsg = {
        id: res.message_id,
        role: "assistant",
        content: res.answer,
        citations: res.citations || [],
        insufficient_evidence: res.insufficient_evidence,
        warnings: res.warnings || [],
        provenance: res.provenance || [],
        // Market-entry context (jurisdiction scope) — present whenever a
        // Product Passport version with target markets frames the question.
        market_context: res.market_context || [],
        jurisdiction_mode: res.jurisdiction_mode || "both",
        jurisdiction_filter: res.jurisdiction_filter || [],
        unselected_jurisdiction_sources_excluded:
          res.unselected_jurisdiction_sources_excluded || [],
        private_search_requested: res.private_search_requested,
        private_search_performed: res.private_search_performed,
        private_sources_found: res.private_sources_found ?? 0,
        public_sources_found: res.public_sources_found ?? 0,
        jurisdiction_warning: res.jurisdiction_warning || "",
        evidence_status: res.evidence_status || null,
        evidence_gap_warnings: res.evidence_gap_warnings || [],
        why_this_answer: res.why_this_answer || null,
        claim_reviews: res.claim_reviews || [],
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
      setAttachments([]);
      speakReply(res.answer);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleNewChat = () => {
    setActiveSessionId(null);
    setMessages([]);
    setAttachments([]);
    setError(null);
  };

  const handleDeleteSession = async (id, e) => {
    e.stopPropagation();
    if (!window.confirm("Delete this conversation?")) return;
    try {
      await api.deleteConversation(accessToken, id);
      toast("Conversation removed successfully");
      if (activeSessionId === id) {
        handleNewChat();
      }
      loadSessions();
    } catch (err) {
      alert("Delete failed: " + err.message);
    }
  };

  return (
    <div className="chat-grid">
      {/* Sidebar: Conversation Sessions & Context Settings */}
      <div className="chat-side">
        <Card title="Conversations">
          <Button onClick={handleNewChat} style={{ width: "100%", marginBottom: "12px" }}>
            + New Chat
          </Button>

          {sessions.length === 0 ? (
            <p className="muted" style={{ fontSize: "12px" }}>No previous chats.</p>
          ) : (
            <ul className="session-list">
              {sessions.map((s) => (
                <li
                  key={s.id}
                  className={"session-item" + (activeSessionId === s.id ? " active" : "")}
                  onClick={() => {
                    setActiveSessionId(s.id);
                    setAttachments([]);
                  }}
                >
                  <span className="st-title">{s.title || `Chat #${s.id}`}</span>
                  <button
                    className="session-del"
                    onClick={(e) => handleDeleteSession(s.id, e)}
                    title="Delete conversation"
                    type="button"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Product Passport Context Injector */}
        <div>
          <Card title="Context Options">
            <div className="field">
              <label>Ground in product passport (optional)</label>
              <select
                value={selectedProductId}
                onChange={(e) => setSelectedProductId(e.target.value)}
              >
                <option value="">-- No Product Context --</option>
                {products.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            {versions.length > 0 && (
              <div className="field">
                <label>Product version</label>
                <select
                  value={selectedVersionId}
                  onChange={(e) => setSelectedVersionId(e.target.value)}
                >
                  {versions.map((v) => (
                    <option key={v.id} value={v.id}>Version {v.version_number}</option>
                  ))}
                </select>
              </div>
            )}

            <label className="checkbox" style={{ fontSize: "12px", marginTop: "10px" }}>
              <input
                type="checkbox"
                checked={includeMyDocs}
                onChange={(e) => setIncludeMyDocs(e.target.checked)}
              />
              Search my private uploaded documents
            </label>

            <div className="field">
              <label>Input language (BHASHINI)</label>
              <select value={inputLanguage} onChange={(e) => setInputLanguage(e.target.value)}>
                <option value="en">English</option>
                <option value="hi">Hindi</option>
                <option value="bn">Bengali</option>
              </select>
            </div>
            <div className="field">
              <label>Answer language (BHASHINI)</label>
              <select value={outputLanguage} onChange={(e) => setOutputLanguage(e.target.value)}>
                <option value="en">English</option>
                <option value="hi">Hindi</option>
                <option value="bn">Bengali</option>
              </select>
            </div>
          </Card>
        </div>
      </div>

      {/* Main Chat Window */}
      <div className="chat-main">
        <Card>
          <div className="chat-toolbar">
            {/* Jurisdiction switch (SIH: national vs international layers kept
                separate). "Both" preserves the passport-market scope. */}
            <div className={"llm-toggle jurisdiction-" + jurisdictionMode} role="group" aria-label="Choose the jurisdiction scope">
              <span className="llm-knob" aria-hidden="true" />
              <button
                type="button"
                className={jurisdictionMode === "both" ? "active" : ""}
                onClick={() => setJurisdictionMode("both")}
                title="Retrieve from all jurisdictions (passport markets decide)"
              >
                Both
              </button>
              <button
                type="button"
                className={jurisdictionMode === "india" ? "active" : ""}
                onClick={() => setJurisdictionMode("india")}
                title="Indian sources only"
              >
                India
              </button>
              <button
                type="button"
                className={jurisdictionMode === "international" ? "active" : ""}
                onClick={() => setJurisdictionMode("international")}
                title="International sources only (treaties and non-Indian regimes)"
              >
                International
              </button>
            </div>
            <div className={"llm-toggle " + llmProvider} role="group" aria-label="Choose the answer provider">
              <span className="llm-knob" aria-hidden="true" />
              <button
                type="button"
                className={llmProvider === "groq" ? "active" : ""}
                onClick={() => chooseProvider("groq")}
              >
                Groq
              </button>
              <button
                type="button"
                className={llmProvider === "sarvam" ? "active" : ""}
                onClick={() => chooseProvider("sarvam")}
              >
                Sarvam
              </button>
            </div>
            <button
              type="button"
              className={"icon-btn reply-voice" + (voiceOn ? " on" : "")}
              onClick={toggleVoice}
              aria-pressed={voiceOn}
              title={voiceOn ? "Spoken replies are on - click to mute" : "Spoken replies are off - click to unmute"}
            >
              {voiceOn ? (
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><path d="M15.54 8.46a5 5 0 0 1 0 7.07" /><path d="M19.07 4.93a10 10 0 0 1 0 14.14" /></svg>
              ) : (
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><line x1="23" y1="9" x2="17" y2="15" /><line x1="17" y1="9" x2="23" y2="15" /></svg>
              )}
            </button>
          </div>

          {/* Messages display */}
          <div className="chat-thread">
            {messages.length === 0 ? (
              <div className="chat-empty">
                <p style={{ fontWeight: 600, fontSize: "15px" }}>Welcome to IP-SAKTI Sahayak</p>
                <p style={{ fontSize: "13.5px" }}>
                  Ask anything grounded in the verified regulatory corpus or your own documents.
                </p>
                <p className="ex">
                  Example: "What are the patent criteria for Ashwagandha under Section 3(p)?"
                </p>
              </div>
            ) : (
              messages.map((m, idx) => (
                <div
                  key={idx}
                  style={{
                    alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: "min(85%, 760px)",
                  }}
                >
                  <div className={m.role === "user" ? "bubble bubble-user" : "bubble bubble-ai"}>
                    {/* Market-entry context (jurisdiction scope) */}
                    {m.role === "assistant" && <ChatMarketPanel m={m} />}

                    <div>
                      {m.content}
                    </div>

                    {/* Insufficient Evidence Notice */}
                    {m.insufficient_evidence && (
                      <div className="chat-notice">
                        The verified corpus doesn't contain enough evidence to fully answer this question.
                      </div>
                    )}

                    {/* Citations & Evidence Section */}
                    {m.citations && m.citations.length > 0 && (
                      <div className="chat-cites">
                        <div className="chat-cites-head">
                          Sources & citations ({m.citations.length})
                          {m.provenance && m.provenance.length > 0 && (
                            <span className="prov">Provenance: {m.provenance.join(", ")}</span>
                          )}
                        </div>
                        <div>
                          {m.citations.map((c, cIdx) => (
                            <div className="chat-cite" key={cIdx}>
                              <div className="ct">
                                [{cIdx + 1}] {c.title} {c.jurisdiction && `(${c.jurisdiction})`} · <span style={{ textTransform: "capitalize" }}>{String(c.source_type || "").replace(/_/g, " ")}</span>
                                {c.confidence_label && (
                                  <span
                                    className={"conf conf-" + String(c.confidence_label).toLowerCase()}
                                    title={"Relative match strength within this answer (0-1), not a probability: " + (c.confidence_score ?? "n/a")}
                                  >
                                    · {c.confidence_label}
                                  </span>
                                )}
                              </div>
                              {c.relevant_text && (
                                <blockquote>
                                  &ldquo;{c.relevant_text}&rdquo;
                                </blockquote>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}

            {loading && <AyurvedaActivityIndicator active={loading} />}
          </div>

          <FormError message={error} />

          {/* Attached PDFs */}
          {(attachments.length > 0 || uploadingAttachment) && (
            <div className="chat-chips">
              {uploadingAttachment && <span className="chip busy">Parsing PDF...</span>}
              {attachments.map((a) => (
                <span
                  className="chip"
                  key={a.id}
                  title={`${a.char_count.toLocaleString()} characters read from this PDF${a.truncated ? " (long documents are used up to a limit)" : ""}`}
                >
                  {a.filename}
                  <button
                    type="button"
                    onClick={() => {
                      setAttachments((prev) => prev.filter((x) => x.id !== a.id));
                      toast("Attachment removed");
                    }}
                    title="Remove attachment"
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
          )}

          {/* Input Form */}
          <form onSubmit={handleSend} className="chat-input-row">
            <button
              type="button"
              className="icon-btn"
              onClick={() => fileInputRef.current && fileInputRef.current.click()}
              disabled={uploadingAttachment}
              title="Attach a PDF research document"
              aria-label="Attach a PDF"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" /></svg>
            </button>
            <input
              type="file"
              accept="application/pdf,.pdf"
              ref={fileInputRef}
              onChange={handleFileSelect}
              style={{ display: "none" }}
            />
            <input
              type="text"
              className="input-line"
              placeholder="Type your question — e.g. How do I document biodiversity origin?"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              disabled={loading}
            />
            <button
              type="button"
              className={"icon-btn mic-btn" + (listening ? " listening" : "")}
              onClick={listening ? stopListening : startListening}
              title={listening ? "Stop listening" : "Speak your question"}
              aria-label="Speak your question"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" y1="19" x2="12" y2="23" /><line x1="8" y1="23" x2="16" y2="23" /></svg>
            </button>
            <Button disabled={loading || uploadingAttachment || !inputMessage.trim()} type="submit">
              {loading ? "Thinking…" : uploadingAttachment ? "Uploading…" : "Send"}
            </Button>
          </form>
        </Card>
      </div>
    </div>
  );
}

// ---- Styles --------------------------------------------------------------

const css = `
  /* Layout */
  #root { width: 100%; max-width: none; margin: 0; border: none; text-align: left; }
  .layout { min-height: 100vh; display: flex; background: #FAF5EC; color: #1C2420; color-scheme: light; }
  .sidebar { width: 248px; flex-shrink: 0; background: #FFFDF8; border-right: 1px solid #E4DACA; display: flex; flex-direction: column; position: sticky; top: 0; height: 100vh; transition: width 200ms ease; }
  .sidebar.collapsed { width: 78px; }
  .side-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 16px 14px; border-bottom: 1px solid #EFE7D5; }
  .brand { display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 700; color: #1E3A2F; text-decoration: none; white-space: nowrap; overflow: hidden; }
  .brand span { overflow: hidden; text-overflow: ellipsis; }
  .side-toggle { width: 36px; height: 36px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 8px; border: 1px solid #E4DACA; background: #FAF5EC; color: #1E3A2F; cursor: pointer; transition: transform 180ms ease, background 180ms ease; }
  .side-toggle:hover { transform: translateY(-2px); background: #F1E9D6; }
  .side-toggle svg { transition: transform 200ms ease; }
  .side-nav { display: flex; flex-direction: column; gap: 6px; padding: 16px 12px; flex: 1; overflow-y: auto; }
  .side-link { display: flex; align-items: center; gap: 12px; padding: 11px 12px; border-radius: 8px; color: #43524A; text-decoration: none; font-size: 14.5px; font-weight: 600; white-space: nowrap; transition: transform 180ms ease, background 180ms ease, box-shadow 180ms ease, color 180ms ease; }
  .side-link:hover { transform: translateY(-3px); background: #F5EEDF; color: #1C2420; box-shadow: 0 10px 20px -12px rgba(30,58,47,.45); }
  .side-link.active { background: #1E3A2F; color: #FAF5EC; }
  .sidebar.collapsed .side-link { justify-content: center; padding: 11px 0; }
  .sidebar.collapsed .side-top { flex-direction: column; }
  .side-profile { position: relative; border-top: 1px solid #EFE7D5; padding: 12px; }
  .profile-btn { display: flex; align-items: center; gap: 10px; width: 100%; background: none; border: none; cursor: pointer; padding: 8px; border-radius: 8px; text-align: left; color: inherit; font: inherit; }
  .profile-btn:hover { background: #F5EEDF; }
  .avatar { width: 36px; height: 36px; border-radius: 50%; background: #1E3A2F; color: #FAF5EC; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: 15px; flex-shrink: 0; }
  .profile-meta { min-width: 0; }
  .profile-meta b { display: block; font-size: 13.5px; color: #1C2420; max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .profile-meta span { font-size: 12px; color: #6B7280; }
  .sidebar.collapsed .profile-btn { justify-content: center; }
  .profile-menu { position: absolute; left: 12px; right: 12px; bottom: calc(100% + 6px); z-index: 30; border: 1px solid #E7DFCE; border-radius: 8px; padding: 12px; background: #fff; box-shadow: 0 12px 24px -14px rgba(28, 36, 32, 0.45); }
  .profile-id { font-size: 13px; font-weight: 600; color: #1C2420; margin: 0 0 10px; overflow: hidden; text-overflow: ellipsis; }
  .profile-menu .btn { width: 100%; }
  .side-content { flex: 1; min-width: 0; display: flex; flex-direction: column; }
  .main { flex: 1; padding: 24px 32px 48px; max-width: 1280px; margin: 0 auto; width: 100%; box-sizing: border-box; }
  .main-wide { max-width: none; padding: 20px 24px; }
  @media (max-width: 860px) {
    .layout { flex-direction: column; }
    .sidebar { width: 100%; height: auto; position: static; flex-direction: row; align-items: center; border-right: none; border-bottom: 1px solid #E4DACA; }
    .sidebar.collapsed { width: 100%; }
    .side-top { border-bottom: none; padding: 10px 12px; }
    .side-nav { flex-direction: row; overflow-x: auto; padding: 8px; }
    .side-link { white-space: nowrap; }
    .side-profile { border-top: none; padding: 8px; }
    .profile-meta, .profile-menu { display: none; }
  }

  /* Cards */
  .card { background: #FFFDF8; border: 1px solid #E7DFCE; border-radius: 12px; padding: 26px 28px; box-shadow: 0 1px 2px rgba(28, 36, 32, 0.04); }
  .card-title { margin: 0 0 16px; font-family: "Times New Roman", Times, serif; font-size: 21px; font-weight: 500; line-height: 1.3; letter-spacing: -0.01em; color: #1C2420; }
  .card-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
  .empty { color: #5B6670; margin: 8px 0; }

  /* Forms */
  .auth-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #f7f6f2; }
  .auth-card { width: 100%; max-width: 360px; background: #fff; border: 1px solid #dcd7cc; border-radius: 8px; padding: 32px; }
  .auth-card h1 { margin: 0 0 24px; font-size: 22px; font-weight: 600; }
  .auth-switch { margin-top: 18px; font-size: 13px; text-align: center; color: #4b4f54; }
  .auth-switch a { color: #0f5257; text-decoration: none; font-weight: 600; }

  .field { margin-bottom: 14px; }
  .field > label { display: block; font-size: 11.5px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; margin-bottom: 7px; color: #6B5E43; }
  .field > label.checkbox { display: flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 400; letter-spacing: normal; text-transform: none; color: #4b4f54; margin-bottom: 0; cursor: pointer; }
  .field input, .field select {
    width: 100%; padding: 11px 13px; border: 1px solid #E4DACA;
    border-radius: 8px; font-size: 14.5px; background: #FAF5EC; color: #1C2420;
  }
  .field input:focus, .field select:focus, textarea:focus {
    outline: 2px solid #1E3A2F; outline-offset: 1px; border-color: transparent;
  }
  textarea { width: 100%; padding: 10px 12px; border: 1px solid #dcd7cc; border-radius: 6px; font-size: 14px; background: #f7f6f2; resize: vertical; }

  .inline-form { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  .inline-form .input { width: 160px; }
  .inline-form textarea { width: 100%; margin-bottom: 4px; }

  /* Buttons */
  .btn { padding: 10px 20px; border: 1px solid transparent; border-radius: 999px; background: #1E3A2F; color: #FAF5EC; font-size: 14px; font-weight: 600; letter-spacing: 0.01em; cursor: pointer; transition: background 160ms ease, transform 160ms ease, box-shadow 160ms ease; }
  .btn:hover:not(:disabled) { background: #152A22; transform: translateY(-1px); box-shadow: 0 8px 16px -10px rgba(30, 58, 47, 0.55); }
  .btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; box-shadow: none; }
  .btn-danger { background: transparent; color: #A33226; border-color: #E0C2BC; }
  .btn-danger:hover:not(:disabled) { background: #FBF0EE; border-color: #A33226; box-shadow: none; }
  .btn-ghost { background: transparent; color: #1E3A2F; border: 1px solid #D9CFB8; }
  .btn-ghost:hover:not(:disabled) { background: #F3EBDA; box-shadow: none; }
  .btn-small { padding: 7px 15px; font-size: 13px; }

  /* Lists */
  .product-list, .version-list, .list { list-style: none; padding: 0; margin: 0; }
  .product-item, .version-item, .list-item {
    display: flex; align-items: center; gap: 14px;
    padding: 15px 18px; border: 1px solid #E7DFCE; border-radius: 10px; margin-bottom: 10px;
    background: #FFFDF8; transition: border-color 160ms ease, box-shadow 160ms ease;
  }
  .product-item:hover, .version-item:hover, .list-item:hover {
    border-color: #C9B98F; box-shadow: 0 8px 18px -14px rgba(28, 36, 32, 0.5);
  }
  .product-info, .version-info, .item-body { flex: 1; min-width: 0; }
  .product-info strong, .version-info strong { font-size: 14px; }
  .item-body > strong { display: block; font-size: 15px; font-weight: 600; color: #1C2420; line-height: 1.4; margin-bottom: 7px; }
  .product-info p, .version-info p { margin: 4px 0; font-size: 13px; color: #4b4f54; }
  .muted { color: #5B6670; font-size: 13.5px; }
  .version-meta { display: flex; gap: 8px; margin-top: 6px; font-size: 13px; align-items: baseline; }

  /* KV */
  .kv { display: grid; grid-template-columns: 180px 1fr; gap: 8px 16px; font-size: 13px; margin-top: 8px; }
  .kv dt { color: #4b4f54; }
  .kv dd { margin: 0; }

  /* Badges */
  .badge {
    display: inline-block; padding: 3px 9px; border-radius: 999px;
    background: #F3ECDC; border: 1px solid #E7DFCE; color: #5B6670;
    font-size: 10.5px; font-weight: 600; line-height: 1.5; letter-spacing: 0.05em;
    text-transform: uppercase; margin-left: 6px; vertical-align: middle;
  }

  /* Misc */
  .section { border-top: 1px solid #e5e4e7; padding: 16px 0; margin-bottom: 0; }
  .section-title { font-size: 14px; font-weight: 600; color: #4b4f54; display: flex; align-items: center; gap: 8px; }
  .version-reason { margin: 0 0 6px; font-size: 14px; }
  .checkbox { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #4b4f54; cursor: pointer; }
  .checkbox input { width: 14px; height: 14px; }
  .form-error { margin: 8px 0; font-size: 13px; color: #b3261e; }
  .form-success { margin: 8px 0; font-size: 13px; color: #1e6b3a; }

  .page-center { min-height: 60vh; display: flex; align-items: stretch; justify-content: center; }
  .page-center > * { width: 100%; }
  /* Pages that hold more than one card stack them instead of placing them side by side. */
  .page-stack { display: flex; flex-direction: column; gap: 16px; }
  .page-stack > * { width: 100%; }

  .stat-box {
    background: #FAF5EC; border: 1px solid #E7DFCE; border-radius: 10px;
    padding: 14px 18px; display: flex; flex-direction: column; min-width: 118px;
  }
  .stat-box strong { font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: -0.01em; color: #1C2420; }
  .stat-box span { font-size: 10.5px; font-weight: 700; letter-spacing: 0.09em; text-transform: uppercase; color: #6B5E43; margin-top: 4px; }

  /* Analysis (Phase 5) */
  .analysis-toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 12px 0; }
  .analysis-result { margin-top: 12px; }
  .analysis-summary-card { border: 1px solid #0f525744; background: #f2f7f7; border-radius: 6px; padding: 4px 12px 10px; margin-top: 12px; }
  .analysis-summary-card .feature-table th { width: 34%; }
  .why-this-result { border: 1px dashed #0f525788; border-radius: 6px; padding: 8px 12px; margin: 10px 0; background: #fafcfc; }
  .why-this-result > summary { cursor: pointer; font-size: 13px; font-weight: 600; color: #0f5257; }
  .why-this-result[open] > summary { margin-bottom: 6px; }
  .subheading { font-size: 13px; font-weight: 600; color: #0f5257; margin: 16px 0 8px; }
  .badge-row { display: flex; flex-wrap: wrap; align-items: center; gap: 2px; margin-bottom: 6px; }
  .badge-row .badge { margin-left: 0; }
  .assessment {
    border: 1px solid #e5e4e7; border-left: 3px solid #0f5257; border-radius: 6px;
    padding: 12px; margin-bottom: 10px; background: #fff;
  }
  .assessment-text { margin: 0 0 6px; font-size: 14px; }
  .assessment-rationale { margin: 6px 0; font-size: 13px; color: #4b4f54; }
  .citation {
    padding: 8px; background: #f2f7f7; border-radius: 4px; font-size: 12px;
    border-left: 3px solid #0f5257; margin-top: 6px;
  }
  .citation blockquote { margin: 4px 0 0; font-style: italic; color: #444; }
  .missing-list { margin: 6px 0 0 18px; font-size: 13px; color: #4b4f54; }
  .missing-list li { margin-bottom: 2px; }
  .change-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin: 8px 0; }
  .change-toolbar select { padding: 4px 6px; border: 1px solid #ccc; border-radius: 4px; }
  .feature-table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12px; }
  .feature-table th, .feature-table td { text-align: left; padding: 4px 6px; border-bottom: 1px solid #eee; }
  .feature-table th { color: #6b7280; font-weight: 600; }
  .notice { padding: 8px 10px; border-radius: 4px; font-size: 12px; margin: 8px 0; }
  .notice-warn { background: #fff3cd; border: 1px solid #ffeeba; color: #856404; }
  .notice-info { background: #eef6ff; border: 1px solid #cfe3ff; color: #1f4e79; }
  .notice-locked { background: #f3e8ff; border: 1px solid #e0c9ff; color: #5b2c8a; }

  /* Knowledge Base page */
  .kb-head { padding: 6px 0 22px; }
  .kb-eyebrow { font-size: 12px; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase; color: #6B5E43; margin: 0 0 12px; }
  .kb-h1 { font-family: "Times New Roman", Times, serif; font-weight: 400; font-size: clamp(28px, 3vw, 40px); line-height: 1.15; letter-spacing: -0.01em; color: #1C2420; margin: 0 0 10px; }
  .kb-sub { font-size: 15px; line-height: 1.55; color: #5B6670; max-width: 720px; margin: 0; }
  .kb-stats { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin-bottom: 20px; }
  .kb-stats .stat-box { min-width: 0; }
  .kb-form { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 14px; }
  .field > label.kb-file {
    display: flex; align-items: center; gap: 10px; margin-bottom: 0;
    text-transform: none; letter-spacing: normal; font-size: 14px; font-weight: 400; color: #5B6670;
    border: 1px dashed #C9B98F; background: #FAF5EC; border-radius: 8px; padding: 13px 15px;
    cursor: pointer; transition: border-color 160ms ease, background 160ms ease;
  }
  .field > label.kb-file:hover { border-color: #1E3A2F; background: #F5EEDF; }
  .field > label.kb-file.has { border-style: solid; border-color: #1E3A2F; color: #1C2420; font-weight: 600; }
  .kb-file svg { flex-shrink: 0; color: #6B5E43; }
  .kb-file input[type="file"] { position: absolute; width: 1px; height: 1px; opacity: 0; padding: 0; border: 0; }
  .kb-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
  .kb-doc-actions { display: flex; gap: 8px; flex-shrink: 0; }
  .kb-error { color: #A33226; font-size: 12.5px; margin: 6px 0 0; }
  @media (max-width: 1000px) {
    .kb-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .kb-form { grid-template-columns: 1fr; }
  }

  /* Shared page header (Reviews, Dashboard, Demo) */
  .pg-head { padding: 6px 0 20px; }
  .pg-eyebrow { font-size: 12px; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase; color: #6B5E43; margin: 0 0 12px; }
  .pg-h1 { font-family: "Times New Roman", Times, serif; font-weight: 400; font-size: clamp(28px, 3vw, 40px); line-height: 1.15; letter-spacing: -0.01em; color: #1C2420; margin: 0 0 10px; }
  .pg-sub { font-size: 15px; line-height: 1.55; color: #5B6670; max-width: 760px; margin: 0; }
  .subheading { color: #1E3A2F; }

  /* Stat grids (Dashboard) */
  .dash-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
  .dash-stats .stat-box { min-width: 0; }

  /* Simple data rows (Dashboard lists, Reviews queue) */
  .row-item { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border: 1px solid #E7DFCE; border-radius: 10px; margin-bottom: 8px; background: #FFFDF8; font-size: 14px; }
  .row-item.row-click { width: 100%; text-align: left; font: inherit; color: inherit; cursor: pointer; transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease; }
  .row-item.row-click:hover { border-color: #C9B98F; box-shadow: 0 8px 18px -14px rgba(28, 36, 32, 0.5); transform: translateY(-1px); }
  .row-id { font-weight: 700; color: #1E3A2F; font-variant-numeric: tabular-nums; flex-shrink: 0; }
  .row-meta { margin-left: auto; color: #5B6670; font-size: 13px; flex-shrink: 0; }

  /* Reviews */
  .rv-form { display: grid; grid-template-columns: 2fr 1fr 2fr auto; gap: 14px; align-items: end; }
  .rv-form .field { margin-bottom: 0; min-width: 0; }
  .rv-form .field input, .rv-form .field select { width: 100%; max-width: 100%; }
  .rv-form .field .btn { white-space: nowrap; flex-shrink: 0; }
  .demo-fields .field { margin-bottom: 0; }
  .rv-comment-row { display: flex; gap: 10px; margin-top: 12px; }
  .input-line { flex: 1; min-width: 0; padding: 11px 16px; border: 1px solid #E4DACA; border-radius: 999px; background: #FAF5EC; font-size: 14.5px; color: #1C2420; }
  .input-line:focus { outline: 2px solid #1E3A2F; outline-offset: 1px; border-color: transparent; }
  .rv-comment { padding: 10px 14px; border-left: 3px solid #E4DACA; background: #FAF5EC; border-radius: 0 8px 8px 0; margin-bottom: 8px; font-size: 14px; }
  .rv-comment b { color: #1C2420; }
  .rv-actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }

  /* Chat */
  .chat-grid { display: grid; grid-template-columns: 300px 1fr; gap: 20px; align-items: stretch; height: calc(100vh - 40px); min-height: 560px; }
  .chat-side { display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow-y: auto; }
  .chat-side > .card { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 150px; }
  .chat-side > div { flex: 0 0 auto; }
  .chat-side .session-list { flex: 1 1 auto; overflow-y: auto; min-height: 0; }
  .chat-main { display: flex; flex-direction: column; min-height: 0; }
  .chat-main > .card { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; }
  .session-list { list-style: none; padding: 0; margin: 0; }
  .session-item { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 6px; font-size: 13.5px; background: #FAF5EC; border: 1px solid #E7DFCE; color: #43524A; transition: border-color 160ms ease, background 160ms ease, transform 160ms ease; }
  .session-item:hover { border-color: #C9B98F; background: #F5EEDF; transform: translateY(-1px); }
  .session-item.active { background: #1E3A2F; border-color: #1E3A2F; color: #FAF5EC; }
  .session-item .st-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .session-del { background: none; border: none; cursor: pointer; color: #98A09B; font-size: 14px; line-height: 1; padding: 3px 5px; border-radius: 5px; flex-shrink: 0; }
  .session-del:hover { color: #A33226; background: #FBF0EE; }
  .session-item.active .session-del { color: #B9C2B8; }
  .session-item.active .session-del:hover { color: #F2B8B1; background: rgba(255, 255, 255, 0.12); }
  .chat-thread { flex: 1 1 auto; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; padding: 16px; background: #FAF5EC; border: 1px solid #E7DFCE; border-radius: 10px; margin-bottom: 16px; }
  .chat-empty { text-align: center; color: #5B6670; padding: 44px 10px; margin: auto; max-width: 460px; }
  .chat-empty p { margin: 4px 0; }
  .chat-empty .ex { font-size: 12.5px; color: #6B7280; }
  .bubble { padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.55; white-space: pre-wrap; }
  .bubble-user { background: #1E3A2F; color: #FAF5EC; }
  .bubble-ai { background: #FFFDF8; color: #1C2420; border: 1px solid #E7DFCE; box-shadow: 0 1px 2px rgba(28, 36, 32, 0.05); }
  .bubble-role { font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; opacity: 0.75; margin-bottom: 5px; }
  .chat-notice { margin-top: 8px; padding: 8px 11px; background: #FFF7E0; border: 1px solid #EADCA8; border-radius: 8px; font-size: 12.5px; color: #7A5F10; }
  .chat-cites { margin-top: 12px; border-top: 1px solid #EFE7D5; padding-top: 9px; }
  .chat-cites-head { font-size: 12px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: #1E3A2F; margin-bottom: 6px; }
  .chat-cites-head .prov { font-weight: 400; letter-spacing: normal; text-transform: none; color: #5B6670; margin-left: 8px; }
  .chat-cite { padding: 9px 11px; background: #F6F2E5; border-radius: 8px; font-size: 12.5px; border-left: 3px solid #1E3A2F; margin-bottom: 6px; }
  .chat-cite .ct { font-weight: 600; color: #1E3A2F; }
  .chat-cite .conf { font-weight: 700; font-size: 11px; letter-spacing: 0.04em; padding: 1px 7px; border-radius: 999px; margin-left: 2px; white-space: nowrap; }
  .chat-cite .conf-high { background: #E3EFE4; color: #1E5B33; border: 1px solid #BFDCC4; }
  .chat-cite .conf-medium { background: #FBF3DC; color: #7A5B00; border: 1px solid #EAD9A0; }
  .chat-cite .conf-low { background: #F9E8E4; color: #8A2E1F; border: 1px solid #EBC2B8; }
  .chat-cite blockquote { margin: 5px 0 0; font-style: italic; color: #5B6670; }
  /* --- Market-entry context panel (jurisdiction scope) --- */
  .market-panel { white-space: normal; margin: -4px 0 12px; padding: 10px 12px; background: #F4F7F3; border: 1px solid #DCE6DC; border-radius: 9px; font-size: 12.5px; line-height: 1.5; }
  .mp-block { margin-bottom: 9px; }
  .mp-block:last-child { margin-bottom: 0; }
  .mp-head { font-size: 11px; font-weight: 700; letter-spacing: 0.07em; text-transform: uppercase; color: #1E3A2F; margin-bottom: 3px; }
  .mp-block ul { margin: 2px 0 0; padding-left: 4px; list-style: none; }
  .mp-status { font-weight: 700; color: #8A4B08; }
  .mp-sub { color: #5B6670; margin-top: 2px; }
  .mp-warning { background: #FFF7E0; border: 1px solid #EADCA8; border-radius: 7px; padding: 7px 9px; color: #7A5F10; }
  .mp-gap { margin-top: 6px; padding: 7px 9px; background: #FDEEEE; border: 1px solid #F0C9C9; border-radius: 7px; color: #8C2F2F; font-weight: 600; }
  .mp-why { margin-top: 8px; border-top: 1px solid #DCE6DC; padding-top: 6px; }
  .mp-why summary { cursor: pointer; font-weight: 700; color: #1E3A2F; font-size: 12.5px; }
  .mp-why-body { margin-top: 7px; }
  .mp-why-row { margin-bottom: 7px; }
  .mp-why-row ul { margin: 3px 0 0; padding-left: 18px; }
  .mp-claim { background: #FFFDF8; border: 1px solid #E7DFCE; border-radius: 7px; padding: 7px 9px; margin-top: 5px; }
  .mp-claim-text { font-weight: 600; color: #1E3A2F; }
  .mp-claim-meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 5px; }
  .mp-tag { background: #EAF0EA; border: 1px solid #CFDDD1; border-radius: 999px; padding: 2px 8px; font-size: 11.5px; color: #2C4A38; }
  .mp-tag-review { background: #FFF7E0; border-color: #EADCA8; color: #7A5F10; }
  .ai-activity { align-self: flex-start; min-height: 40px; box-sizing: border-box; display: flex; align-items: center; gap: 9px; padding: 10px 15px; background: #FFFDF8; border: 1px solid #E7DFCE; border-radius: 999px; font-size: 13px; color: #5B6670; max-width: min(85%, 760px); }
  .ai-activity-dot { width: 7px; height: 7px; border-radius: 50%; background: #8A9A8E; flex-shrink: 0; animation: ai-dot-pulse 1.9s ease-in-out infinite; }
  .ai-activity-text { display: inline-block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; animation: ai-fade-slide 1.9s ease both; }
  @keyframes ai-fade-slide { 0% { opacity: 0; transform: translateY(6px); } 14% { opacity: 1; transform: translateY(0); } 78% { opacity: 1; transform: translateY(0); } 100% { opacity: 0; transform: translateY(-6px); } }
  @keyframes ai-dot-pulse { 0%, 100% { opacity: 0.45; } 50% { opacity: 1; } }
  @media (prefers-reduced-motion: reduce) {
    .ai-activity-dot { animation: none; opacity: 0.8; }
    .ai-activity-text { animation: ai-fade-only 1.9s ease both; }
  }
  @keyframes ai-fade-only { 0% { opacity: 0; } 14% { opacity: 1; } 78% { opacity: 1; } 100% { opacity: 0; } }
  .chat-input-row { display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
  .chat-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
  .llm-toggle { position: relative; display: inline-flex; background: #FAF5EC; border: 1px solid #E7DFCE; border-radius: 999px; padding: 3px; user-select: none; }
  .llm-toggle .llm-knob { position: absolute; top: 3px; bottom: 3px; left: 3px; width: calc(50% - 3px); background: #1E3A2F; border-radius: 999px; transition: transform 320ms cubic-bezier(0.34, 1.56, 0.64, 1); }
  .llm-toggle.sarvam .llm-knob { transform: translateX(100%); }
  .llm-toggle button { position: relative; z-index: 1; border: none; background: none; cursor: pointer; font: inherit; font-size: 12.5px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; width: 84px; padding: 7px 0; color: #43524A; transition: color 240ms ease; }
  .llm-toggle button.active { color: #FAF5EC; }
  /* Three-way jurisdiction switch: one third per option, two slide steps. */
  .llm-toggle[class*="jurisdiction-"] .llm-knob { width: calc(33.333% - 2px); }
  .llm-toggle.jurisdiction-india .llm-knob { transform: translateX(100%); }
  .llm-toggle.jurisdiction-international .llm-knob { transform: translateX(200%); }
  .llm-toggle[class*="jurisdiction-"] button { width: 110px; }
  .icon-btn { width: 42px; height: 42px; flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; border: 1px solid #E4DACA; background: #FAF5EC; color: #1E3A2F; cursor: pointer; padding: 0; transition: transform 160ms ease, background 160ms ease, border-color 160ms ease, color 160ms ease; }
  .icon-btn:hover { background: #F5EEDF; transform: translateY(-1px); }
  .icon-btn:disabled { opacity: 0.55; cursor: progress; transform: none; }
  .icon-btn.mic-btn.listening { background: #A33226; border-color: #A33226; color: #FFF7F5; animation: mic-pulse 1.3s ease-in-out infinite; }
  @keyframes mic-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(163, 50, 38, 0.35); } 55% { box-shadow: 0 0 0 9px rgba(163, 50, 38, 0); } }
  .icon-btn.reply-voice.on { background: #1E3A2F; border-color: #1E3A2F; color: #FAF5EC; }
  .chat-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
  .chip { display: inline-flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 999px; background: #F6F2E5; border: 1px solid #E7DFCE; font-size: 12.5px; color: #1E3A2F; max-width: 340px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .chip.busy { background: #FFF7E0; border-color: #EADCA8; color: #7A5F10; }
  .chip button { border: none; background: none; cursor: pointer; color: #98A09B; font-size: 13px; line-height: 1; padding: 0; flex-shrink: 0; }
  .chip button:hover { color: #A33226; }

  @media (max-width: 1000px) {
    .chat-grid { grid-template-columns: 1fr; height: auto; }
    .rv-form { grid-template-columns: 1fr; }
    .dash-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }

  /* Responsive */
  @media (max-width: 600px) {
    .inline-form .input { width: 100%; }
    .inline-form { flex-direction: column; align-items: stretch; }
    .product-item, .version-item, .list-item { flex-wrap: wrap; }
  }

  /* Success toasts */
  .toast-stack { position: fixed; top: 18px; right: 18px; z-index: 600; display: flex; flex-direction: column; gap: 10px; width: min(86vw, 360px); pointer-events: none; }
  .toast { pointer-events: auto; display: flex; align-items: center; gap: 11px; padding: 13px 14px; background: #1E3A2F; color: #F2ECDF; border: 1px solid rgba(250, 245, 236, 0.18); border-radius: 12px; box-shadow: 0 18px 40px -18px rgba(28, 36, 32, 0.65); font-size: 13.5px; font-weight: 600; animation: toast-in 260ms cubic-bezier(0.34, 1.3, 0.64, 1); transition: opacity 220ms ease, transform 220ms ease; }
  .toast.out { opacity: 0; transform: translateX(14px); }
  .toast-ico { width: 22px; height: 22px; border-radius: 50%; background: rgba(146, 217, 161, 0.2); color: #A7E0B5; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .toast-msg { flex: 1; min-width: 0; line-height: 1.45; }
  .toast-x { border: none; background: none; color: rgba(242, 236, 223, 0.65); cursor: pointer; font-size: 13px; line-height: 1; padding: 4px 6px; border-radius: 6px; flex-shrink: 0; }
  .toast-x:hover { color: #F2ECDF; background: rgba(255, 255, 255, 0.1); }
  @keyframes toast-in { from { opacity: 0; transform: translateY(-10px) scale(0.97); } to { opacity: 1; transform: none; } }
  @media (max-width: 600px) { .toast-stack { left: 12px; right: 12px; width: auto; } }
`;

// ---- App ------------------------------------------------------------------

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/" element={<Landing />} />
            {/* "/*" so deep links like /products still render the guarded shell. */}
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}
