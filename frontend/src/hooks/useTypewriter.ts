/**
 * 打字机 hook：流式字符渲染。
 *
 * 复刻 ui_flet/state.py StreamState 的关键行为（见 frontend-tauri-refactor.md
 * 第 16 项验收点）：
 * - appendDelta(chunk)：累加到 fullText
 * - tick 用 requestAnimationFrame 推进 shownChars
 * - complete()：立即把 shownChars 推到 fullText 末尾（幂等）
 * - reset()：清空
 * - 断线暂停 tick：外部传 isPaused=true 时停止 tick（重连期间不推进）
 * - 速度：每帧最多渲染 maxCharsPerFrame 个字符（默认 8）
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface UseTypewriterOptions {
  maxCharsPerFrame?: number;
  isPaused?: boolean;
}

export interface UseTypewriterReturn {
  fullText: string;
  shownText: string;
  isTyping: boolean;
  appendDelta: (chunk: string) => void;
  complete: () => void;
  reset: () => void;
}

export function useTypewriter(
  options: UseTypewriterOptions = {},
): UseTypewriterReturn {
  const { maxCharsPerFrame = 8, isPaused = false } = options;

  const [fullText, setFullText] = useState("");
  const [shownText, setShownText] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const rafRef = useRef<number | null>(null);
  // 用 ref 跟踪最新值，避免 RAF 闭包陈旧
  const fullTextRef = useRef("");
  const shownRef = useRef(0);
  const pausedRef = useRef(isPaused);

  useEffect(() => {
    pausedRef.current = isPaused;
  }, [isPaused]);

  const tick = useCallback(() => {
    if (pausedRef.current) {
      rafRef.current = requestAnimationFrame(tick);
      return;
    }
    const full = fullTextRef.current;
    const current = shownRef.current;
    if (current >= full.length) {
      setIsTyping(false);
      rafRef.current = null;
      return;
    }
    const next = Math.min(current + maxCharsPerFrame, full.length);
    shownRef.current = next;
    setShownText(full.slice(0, next));
    rafRef.current = requestAnimationFrame(tick);
  }, [maxCharsPerFrame]);

  const startTick = useCallback(() => {
    if (rafRef.current !== null) return;
    setIsTyping(true);
    rafRef.current = requestAnimationFrame(tick);
  }, [tick]);

  const appendDelta = useCallback(
    (chunk: string) => {
      if (!chunk) return;
      fullTextRef.current += chunk;
      setFullText(fullTextRef.current);
      startTick();
    },
    [startTick],
  );

  const complete = useCallback(() => {
    // 幂等：立即把 shown 推到末尾
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    shownRef.current = fullTextRef.current.length;
    setShownText(fullTextRef.current);
    setIsTyping(false);
  }, []);

  const reset = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    fullTextRef.current = "";
    shownRef.current = 0;
    setFullText("");
    setShownText("");
    setIsTyping(false);
  }, []);

  // 卸载时清理
  useEffect(() => {
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return {
    fullText,
    shownText,
    isTyping,
    appendDelta,
    complete,
    reset,
  };
}
