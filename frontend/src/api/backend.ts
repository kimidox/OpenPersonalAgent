/**
 * 后端连接配置（阶段 6：Tauri sidecar 注入）。
 *
 * 三种运行模式：
 * 1. 浏览器 dev：VITE_BACKEND_URL 为空，vite proxy 转发 /api 与 /ws
 * 2. Tauri dev：BACKEND_DEV=1，Rust 拉起 python -m uvicorn，invoke 取 URL/token
 * 3. Tauri 打包：Rust 拉起 sidecar exe，invoke 取 URL/token
 *
 * 见 frontend-tauri-refactor.md 3.12 节。
 */

let baseUrl = import.meta.env.VITE_BACKEND_URL ?? "";
let token = import.meta.env.VITE_BACKEND_TOKEN ?? "";

/** 是否运行在 Tauri WebView 中（window.__TAURI_INTERNALS__ 由 Tauri 2 注入）。 */
export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function getBaseUrl(): string {
  return baseUrl;
}

export function getToken(): string {
  return token;
}

export function getWsUrl(): string {
  if (baseUrl) {
    const host = new URL(baseUrl).host;
    return `ws://${host}/ws/stream`;
  }
  // dev 模式：vite proxy 转发 /ws → 后端 :8765
  return "/ws/stream";
}

/** 注入后端配置（Tauri invoke 返回后调用）。 */
export function setBackendConfig(url: string, tkn: string): void {
  baseUrl = url;
  token = tkn;
}

/**
 * 初始化后端配置：Tauri 模式下调 invoke('get_backend_url') 获取 URL/token；
 * 浏览器模式直接返回（依赖 vite proxy）。
 *
 * 应在 React 渲染前调用一次。
 */
export async function initBackendConfig(): Promise<void> {
  if (!isTauri()) {
    return;
  }
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const info = await invoke<{
      base_url: string;
      ws_url: string;
      token: string;
      ready: boolean;
    }>("get_backend_url");
    if (info?.ready) {
      setBackendConfig(info.base_url, info.token);
      console.info("[backend] Tauri 注入:", info.base_url);
    } else {
      // 后端尚未就绪 → 监听 backend-ready 事件
      const { listen } = await import("@tauri-apps/api/event");
      await listen<typeof info>("backend-ready", (e) => {
        if (e.payload?.ready) {
          setBackendConfig(e.payload.base_url, e.payload.token);
          console.info("[backend] Tauri 事件注入:", e.payload.base_url);
        }
      });
    }
  } catch (err) {
    console.error("[backend] Tauri invoke 失败:", err);
  }
}
