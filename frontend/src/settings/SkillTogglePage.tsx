/**
 * Skill 开关管理页：启用/禁用 + 会话绑定编辑。
 *
 * 对应 ui_flet/settings/skill_toggle_page.py。
 */
import { useCallback, useEffect, useState } from "react";
import { api, APIError } from "@/api/client";
import type { SkillSummary } from "@/types/api";
import Modal from "@/components/Modal";
import { SettingsPageLayout, SettingsSection } from "./SettingsSection";
import Toggle from "./Toggle";

const CONVERSATION_TYPES = [
  { key: "agent_conversation", label: "智能体会话" },
  { key: "human_chat_conversation", label: "聊天会话" },
  { key: "record_conversation", label: "录音会话" },
] as const;

export default function SkillTogglePage() {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [bindings, setBindings] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [editing, setEditing] = useState<SkillSummary | null>(null);
  const [editChecked, setEditChecked] = useState<Record<string, boolean>>({});
  const [savingBindings, setSavingBindings] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [skillList, bindResp] = await Promise.all([
        api.listSkills(),
        api.getSkillBindings(),
      ]);
      setSkills(skillList);
      setBindings(bindResp.bindings ?? {});
      setStatus(null);
    } catch (err) {
      setStatus(`加载失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleToggle = useCallback(
    async (skill: SkillSummary, disabled: boolean) => {
      setStatus(null);
      try {
        await api.toggleSkill(skill.id, disabled);
        setSkills((prev) =>
          prev.map((s) =>
            s.id === skill.id ? { ...s, is_disabled: disabled } : s,
          ),
        );
        setStatus(disabled ? `已禁用：${skill.name}` : `已启用：${skill.name}`);
      } catch (err) {
        setStatus(`切换失败：${err instanceof APIError ? err.detail : err}`);
      }
    },
    [],
  );

  const openBindings = useCallback(
    (skill: SkillSummary) => {
      setEditing(skill);
      const checked: Record<string, boolean> = {};
      for (const t of CONVERSATION_TYPES) {
        checked[t.key] = (bindings[t.key] ?? []).includes(skill.id);
      }
      setEditChecked(checked);
    },
    [bindings],
  );

  const handleSaveBindings = useCallback(async () => {
    if (!editing) return;
    setSavingBindings(true);
    setStatus(null);
    try {
      const next: Record<string, string[]> = {};
      for (const t of CONVERSATION_TYPES) {
        const existing = bindings[t.key] ?? [];
        const shouldInclude = !!editChecked[t.key];
        if (shouldInclude) {
          next[t.key] = existing.includes(editing.id)
            ? existing
            : [...existing, editing.id];
        } else {
          next[t.key] = existing.filter((id) => id !== editing.id);
        }
      }
      for (const key of Object.keys(bindings)) {
        if (!(key in next)) next[key] = bindings[key];
      }
      const resp = await api.setSkillBindings(next);
      setBindings(resp.bindings ?? next);
      setStatus(`已保存会话绑定：${editing.name}`);
      setEditing(null);
    } catch (err) {
      setStatus(`保存失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSavingBindings(false);
    }
  }, [editing, editChecked, bindings]);

  const disabledCount = skills.filter((s) => s.is_disabled).length;

  return (
    <SettingsPageLayout
      title="Skill 开关管理"
      description="启用或禁用已加载的 Skill。禁用的 Skill 不会被 SkillAgent 加载和使用。点击编辑按钮可配置 Skill 在不同会话类型中的默认启用状态。"
      status={status ?? undefined}
    >
      <SettingsSection
        title="已加载 Skill 列表"
        headerActions={
          <button
            className="settings-btn icon-only ghost"
            onClick={load}
            disabled={loading}
            title="刷新"
          >
            ↻
          </button>
        }
      >
        {loading ? (
          <div className="settings-loading">加载中...</div>
        ) : skills.length === 0 ? (
          <div className="settings-empty">暂无 Skill</div>
        ) : (
          <div className="settings-list">
            {skills.map((s) => (
              <div key={s.id} className="settings-list-item skill-item">
                <Toggle
                  checked={!s.is_disabled}
                  onChange={(checked) => handleToggle(s, !checked)}
                />
                <span className="skill-status-label">
                  {s.is_disabled ? "禁用" : "启用"}
                </span>
                <div className="list-item-main">
                  <div className="list-item-title">
                    {s.id} · {s.name || "(未命名)"}
                    <span
                      className={`settings-tag ${s.is_builtin ? "info" : "success"}`}
                    >
                      {s.is_builtin ? "内置" : "用户"}
                    </span>
                    {s.is_disabled && (
                      <span className="settings-tag error">已禁用</span>
                    )}
                  </div>
                </div>
                <button
                  className="settings-btn icon-only ghost skill-edit-btn"
                  onClick={() => openBindings(s)}
                  title="编辑会话绑定"
                >
                  ✎
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="settings-status info" style={{ marginTop: 12 }}>
          共 {skills.length} 个 Skill，已禁用 {disabledCount} 个
        </div>
      </SettingsSection>

      <Modal
        title="编辑会话绑定"
        open={!!editing}
        onClose={() => setEditing(null)}
        maxWidth={480}
        footer={
          <>
            <button
              className="settings-btn"
              onClick={() => setEditing(null)}
              disabled={savingBindings}
            >
              取消
            </button>
            <button
              className="settings-btn primary"
              onClick={handleSaveBindings}
              disabled={savingBindings}
            >
              {savingBindings ? "保存中..." : "保存"}
            </button>
          </>
        }
      >
        {editing && (
          <div>
            <div style={{ marginBottom: 12 }}>
              <div className="list-item-title">{editing.name}</div>
              <div className="list-item-meta">ID: {editing.id}</div>
            </div>
            {CONVERSATION_TYPES.map((t) => (
              <label
                key={t.key}
                className="settings-switch"
                style={{ display: "block", marginBottom: 8 }}
              >
                <input
                  type="checkbox"
                  checked={!!editChecked[t.key]}
                  onChange={(e) =>
                    setEditChecked((prev) => ({
                      ...prev,
                      [t.key]: e.target.checked,
                    }))
                  }
                />
                {t.label}（{t.key}）
              </label>
            ))}
          </div>
        )}
      </Modal>
    </SettingsPageLayout>
  );
}
