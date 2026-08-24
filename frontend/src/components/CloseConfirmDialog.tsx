/**
 * 关闭确认弹窗（Tauri 模式专用）。
 *
 * 流程：用户点击主窗口右上角关闭 → Rust on_window_event 拦截
 * （prevent_close）→ emit("close-requested") → 本组件弹出，
 * 用户选择后 invoke 对应 Tauri 命令：
 * - 悬浮窗模式：api.showFloatingBall() 成功后 invoke("hide_main_window")
 * - 最小化到托盘：invoke("hide_main_window")
 * - 退出程序：invoke("quit_app")（Rust 停止 sidecar 后 exit(0)）
 * - 取消：仅关闭弹窗，主窗口保持显示
 *
 * 浏览器 dev 模式（无 __TAURI_INTERNALS__）不监听也不渲染。
 */

import { useEffect, useState } from "react";
import { api } from "@/api/client";
import "./CloseConfirmDialog.css";

const isTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export default function CloseConfirmDialog() {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isTauri) return;
    let unlisten: (() => void) | undefined;
    let cancelled = false;
    import("@tauri-apps/api/event")
      .then(({ listen }) => listen("close-requested", () => setOpen(true)))
      .then((fn) => {
        if (cancelled) fn();
        else unlisten = fn;
      })
      .catch((err) =>
        console.error("[CloseConfirmDialog] 监听 close-requested 失败:", err),
      );
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  if (!open) return null;

  const invoke = async (cmd: string) => {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke(cmd);
  };

  const handleFloatingBall = async () => {
    setBusy(true);
    setError(null);
    try {
      // 先确认悬浮球显示成功，再隐藏主窗口，避免两个窗口都不可见
      await api.showFloatingBall();
      await invoke("hide_main_window");
      setOpen(false);
    } catch (err) {
      console.error("[CloseConfirmDialog] 进入悬浮窗模式失败:", err);
      setError(`进入悬浮窗模式失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleMinimize = async () => {
    setBusy(true);
    setError(null);
    try {
      await invoke("hide_main_window");
      setOpen(false);
    } catch (err) {
      console.error("[CloseConfirmDialog] 最小化到托盘失败:", err);
      setError(`最小化失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const handleQuit = async () => {
    setBusy(true);
    setError(null);
    try {
      // quit_app 内部会停止后端 sidecar 并 exit(0)
      await invoke("quit_app");
    } catch (err) {
      console.error("[CloseConfirmDialog] 退出失败:", err);
      setError(`退出失败：${err instanceof Error ? err.message : String(err)}`);
      setBusy(false);
    }
  };

  const handleCancel = () => {
    if (busy) return;
    setOpen(false);
    setError(null);
  };

  return (
    <div
      className="ccd-overlay"
      onClick={() => {
        if (!busy) handleCancel();
      }}
    >
      <div className="ccd-dialog" onClick={(e) => e.stopPropagation()}>
        <h3 className="ccd-title">关闭主窗口</h3>
        <p className="ccd-subtitle">请选择关闭后的运行方式</p>
        {error && <div className="ccd-error">{error}</div>}
        <div className="ccd-options">
          <button
            className="ccd-option"
            onClick={handleFloatingBall}
            disabled={busy}
          >
            <span className="ccd-option-name">悬浮窗模式</span>
            <span className="ccd-option-desc">隐藏主窗口，仅保留桌面悬浮球</span>
          </button>
          <button
            className="ccd-option"
            onClick={handleMinimize}
            disabled={busy}
          >
            <span className="ccd-option-name">最小化到托盘</span>
            <span className="ccd-option-desc">隐藏窗口，后台继续运行，托盘图标可唤起</span>
          </button>
          <button
            className="ccd-option ccd-option-danger"
            onClick={handleQuit}
            disabled={busy}
          >
            <span className="ccd-option-name">退出程序</span>
            <span className="ccd-option-desc">停止所有服务并完全退出应用</span>
          </button>
        </div>
        <button className="ccd-cancel" onClick={handleCancel} disabled={busy}>
          取消
        </button>
      </div>
    </div>
  );
}
