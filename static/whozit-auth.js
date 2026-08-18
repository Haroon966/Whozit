/** Session cookie auth for Whozit UI when WHOZIT_API_KEY is set. */
(function (global) {
  const KEY_STORAGE = "whozit_api_key_hint";

  async function probeAuth() {
    try {
      const res = await fetch("/health", { credentials: "same-origin" });
      if (!res.ok) return { auth_enabled: false };
      return res.json();
    } catch (_) {
      return { auth_enabled: false };
    }
  }

  async function loginWithKey(apiKey) {
    const res = await fetch("/session", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
      body: JSON.stringify({ api_key: apiKey }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data?.error?.message || "Login failed");
    }
    try { sessionStorage.setItem(KEY_STORAGE, apiKey); } catch (_) {}
    return data;
  }

  async function ensureSession() {
    const health = await probeAuth();
    if (!health.auth_enabled) return health;
    const probe = await fetch("/scopes", { credentials: "same-origin" });
    if (probe.status !== 401) return health;
    let key = "";
    try { key = sessionStorage.getItem(KEY_STORAGE) || ""; } catch (_) {}
    if (!key) {
      key = window.prompt("Whozit API key (stored in this browser tab only):") || "";
    }
    if (!key) throw new Error("API key required");
    await loginWithKey(key);
    return health;
  }

  async function apiFetch(path, opts = {}) {
    await ensureSession();
    const res = await fetch(path, { credentials: "same-origin", ...opts });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && opts._retried !== true) {
      try { sessionStorage.removeItem(KEY_STORAGE); } catch (_) {}
      await ensureSession();
      return apiFetch(path, { ...opts, _retried: true });
    }
    if (!res.ok) {
      throw new Error(data?.error?.message || res.statusText || "Request failed");
    }
    return data;
  }

  global.WhozitAuth = { ensureSession, apiFetch, loginWithKey, probeAuth };
})(window);
