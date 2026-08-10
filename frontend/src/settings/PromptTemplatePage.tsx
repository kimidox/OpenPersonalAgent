/**
 * 系统提示词配置页：按会话类型编辑 Markdown 提示词模板。
 *
 * 对应 ui_flet/settings/prompt_template_page.py。
 * 端点：GET /api/settings/prompt-templates
 *       PUT /api/settings/prompt-templates/{conv_type}
 *       DELETE /api/settings/prompt-templates/{conv_type}
 *       POST /api/settings/prompt-templates/reset
 */
import { useCallback, useEffect, useState } from "react";
import { api, APIError } from "@/api/client";
import { SettingsField, SettingsPageLayout, SettingsSection } from "./SettingsSection";
import MarkdownRenderer from "@/components/MarkdownRenderer";

interface ConvTypeOption {
  value: string;
  label: string;
}

const CONV_TYPES: ConvTypeOption[] = [
  { value: "agent_conversation", label: "智能体会话" },
  { value: "human_chat_conversation", label: "聊天会话" },
  { value: "record_conversation", label: "录音会话" },
];

export default function PromptTemplatePage() {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [selectedType, setSelectedType] = useState<string>("agent_conversation");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.listPromptTemplates();
      setDrafts({ ...resp.templates });
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

  const currentDraft = drafts[selectedType] ?? "";

  const handleDraftChange = (value: string) => {
    setDrafts((prev) => ({ ...prev, [selectedType]: value }));
  };

  const handleSave = useCallback(async () => {
    setSaving(true);
    setStatus(null);
    try {
      await api.updatePromptTemplate(selectedType, currentDraft);
      setStatus("模板已保存");
    } catch (err) {
      setStatus(`保存失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, [selectedType, currentDraft]);

  const handleResetCurrent = useCallback(async () => {
    if (!confirm(`确认重置「${selectedType}」类型的提示词模板为默认值？`)) return;
    setSaving(true);
    setStatus(null);
    try {
      await api.resetPromptTemplate(selectedType);
      await load();
      setStatus("当前类型模板已重置");
    } catch (err) {
      setStatus(`重置失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, [selectedType, load]);

  const handleResetAll = useCallback(async () => {
    if (!confirm("确认重置所有提示词模板为默认值？此操作不可撤销。")) return;
    setSaving(true);
    setStatus(null);
    try {
      await api.resetAllPromptTemplates();
      await load();
      setStatus("所有模板已重置");
    } catch (err) {
      setStatus(`重置失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, [load]);

  if (loading) return <div className="settings-loading">加载中...</div>;

  return (
    <SettingsPageLayout
      title="系统提示词配置"
      description="按会话类型管理 Markdown 系统提示词模板"
      status={status ?? undefined}
    >
      <SettingsSection title="会话类型">
        <SettingsField label="选择会话类型" hint="切换后加载对应模板">
          <select
            className="settings-select"
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
          >
            {CONV_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </SettingsField>
      </SettingsSection>

      <SettingsSection
        title="模板编辑"
        description="左侧 Markdown 编辑，右侧实时预览"
        actions={
          <>
            <button
              className="settings-btn danger"
              onClick={handleResetCurrent}
              disabled={saving}
            >
              重置当前类型
            </button>
            <button
              className="settings-btn danger"
              onClick={handleResetAll}
              disabled={saving}
            >
              重置全部
            </button>
            <button
              className="settings-btn primary"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? "保存中..." : "保存"}
            </button>
          </>
        }
      >
        <div style={{ display: "flex", gap: 16 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <textarea
              className="settings-textarea"
              style={{ minHeight: 360 }}
              value={currentDraft}
              onChange={(e) => handleDraftChange(e.target.value)}
              placeholder="在此输入 Markdown 系统提示词..."
            />
          </div>
          <div
            style={{
              flex: 1,
              minWidth: 0,
              padding: 12,
              border: "1px solid var(--border)",
              borderRadius: 6,
              background: "var(--bg-primary)",
              minHeight: 360,
              overflow: "auto",
            }}
          >
            <MarkdownRenderer content={currentDraft} />
          </div>
        </div>
      </SettingsSection>
    </SettingsPageLayout>
  );
}
