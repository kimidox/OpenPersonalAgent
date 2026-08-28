import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api/client";
import type { SkillSummary, CliPackageSummary } from "@/types/api";
import "./SlashReferenceMenu.css";

export interface SlashEntry {
  kind: "skill" | "cli";
  id: string;
  label: string;
  description: string;
}

interface Props {
  /** 当前输入框中以 "/" 开头的关键字（不含 "/"），用于过滤 */
  filter: string;
  /** 选中某条目：插入 /skill:id 或 /cli:name 到输入框 */
  onSelect: (entry: SlashEntry) => void;
  /** 关闭菜单（Escape 或点击外部） */
  onClose: () => void;
}

/**
 * 「/」强制引用补全菜单
 *
 * 输入以 "/" 开头时弹出，列出已安装的 Skill 与 CLI 包，
 * 选中后向输入框插入 /skill:<id> 或 /cli:<name> 引用标记，
 * 随消息原样发送，由后端剥离标记并强制注入对应文档。
 */
export default function SlashReferenceMenu({ filter, onSelect, onClose }: Props) {
  const [entries, setEntries] = useState<SlashEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([api.listSkills(), api.listCliPackages()])
      .then(([skills, cliPackages]) => {
        if (cancelled) return;
        const skillEntries: SlashEntry[] = (skills as SkillSummary[])
          .filter((s) => !s.is_disabled)
          .map((s) => ({
            kind: "skill" as const,
            id: s.id,
            label: s.name || s.id,
            description: s.description || "",
          }));
        const cliEntries: SlashEntry[] = (cliPackages as CliPackageSummary[]).map(
          (p) => ({
            kind: "cli" as const,
            id: p.name,
            label: p.name,
            description: p.description || "",
          }),
        );
        setEntries([...skillEntries, ...cliEntries]);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const kw = filter.trim().toLowerCase();
    if (!kw) return entries;
    return entries.filter(
      (e) =>
        e.id.toLowerCase().includes(kw) ||
        e.label.toLowerCase().includes(kw) ||
        e.description.toLowerCase().includes(kw),
    );
  }, [entries, filter]);

  useEffect(() => {
    setActiveIndex(0);
  }, [filter]);

  // 键盘导航（挂在 window 上，输入框 keyDown 中对方向键不消费即可冒泡）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
      } else if ((e.key === "Enter" || e.key === "Tab") && !e.ctrlKey && !e.metaKey) {
        if (filtered.length > 0) {
          e.preventDefault();
          onSelect(filtered[activeIndex] ?? filtered[0]);
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [filtered, activeIndex, onSelect, onClose]);

  // 保持活动项可见
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(
      `[data-index="${activeIndex}"]`,
    );
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return (
    <div className="slash-menu" role="listbox" aria-label="强制引用菜单">
      <div className="slash-menu-header">
        强制引用已安装的 Skill / CLI
        <span className="slash-menu-hint">↑↓ 选择 · Enter 确认 · Esc 关闭</span>
      </div>
      <div className="slash-menu-list" ref={listRef}>
        {loading && <div className="slash-menu-empty">加载中...</div>}
        {error && <div className="slash-menu-error">{error}</div>}
        {!loading && !error && filtered.length === 0 && (
          <div className="slash-menu-empty">无匹配项</div>
        )}
        {!loading &&
          filtered.map((entry, i) => (
            <div
              key={`${entry.kind}:${entry.id}`}
              role="option"
              aria-selected={i === activeIndex}
              data-index={i}
              className={`slash-menu-item ${i === activeIndex ? "active" : ""}`}
              onMouseEnter={() => setActiveIndex(i)}
              onMouseDown={(e) => {
                e.preventDefault(); // 避免触发输入框 blur 导致菜单先关闭
                onSelect(entry);
              }}
            >
              <span className={`slash-menu-kind ${entry.kind}`}>
                {entry.kind === "skill" ? "Skill" : "CLI"}
              </span>
              <span className="slash-menu-id">{entry.label}</span>
              <span className="slash-menu-desc">
                {entry.description.length > 60
                  ? `${entry.description.slice(0, 60)}...`
                  : entry.description}
              </span>
            </div>
          ))}
      </div>
    </div>
  );
}
