import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { api, APIError } from "@/api/client";
import type { LLMConfigItem, LLMConfigListResponse } from "@/types/api";
import { SettingsField, SettingsPageLayout, SettingsSection } from "./SettingsSection";
import Toggle from "./Toggle";

const EMPTY_CONFIG: LLMConfigItem = {
  id: null,
  name: "",
  model_name: "",
  api_key: "",
  base_url: "",
  temperature: 0.7,
  top_p: 0.95,
  frequency_penalty: 0.6,
  enable_thinking: false,
  enable_vision: true,
};

export default function ModelConfigPage() {
  const [data, setData] = useState<LLMConfigListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<LLMConfigItem | null>(null);
  const [showKey, setShowKey] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const selectConfig = useCallback(
    (config: LLMConfigItem) => {
      setSelectedId(config.id);
      setEditing({ ...config });
      setStatus(null);
    },
    [],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.listLLMConfigs();
      setData(resp);
      setSelectedId((prev) => {
        const exists = resp.configs.some((c) => c.id === prev);
        if (prev && exists) {
          const cfg = resp.configs.find((c) => c.id === prev);
          if (cfg) setEditing({ ...cfg });
          return prev;
        }
        if (resp.configs.length > 0) {
          const active = resp.configs.find((c) => c.id === resp.active_id);
          const first = active ?? resp.configs[0];
          setEditing({ ...first });
          return first.id ?? null;
        }
        setEditing(null);
        return null;
      });
    } catch (err) {
      setStatus(`加载失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSave = useCallback(async () => {
    if (!editing) return;
    setSaving(true);
    setStatus(null);
    try {
      if (editing.id) {
        await api.updateLLMConfig(editing.id, editing);
        setStatus("配置已更新");
      } else {
        const created = await api.addLLMConfig(editing);
        setSelectedId(created.id);
        setStatus("配置已创建");
      }
      await load();
    } catch (err) {
      setStatus(`保存失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, [editing, load]);

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm("确认删除该配置？")) return;
      try {
        await api.deleteLLMConfig(id);
        if (selectedId === id) {
          setSelectedId(null);
          setEditing(null);
        }
        setStatus("配置已删除");
        await load();
      } catch (err) {
        setStatus(`删除失败：${err instanceof APIError ? err.detail : err}`);
      }
    },
    [selectedId, load],
  );

  const handleSetActive = useCallback(
    async (id: string) => {
      try {
        await api.setActiveLLM(id);
        setStatus("已激活");
        await load();
      } catch (err) {
        setStatus(`激活失败：${err instanceof APIError ? err.detail : err}`);
      }
    },
    [load],
  );

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setEditing({ ...EMPTY_CONFIG });
    setStatus(null);
  }, []);

  const handleExport = useCallback(() => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data.configs, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `llm-configs-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    setStatus("配置已导出");
  }, [data]);

  const handleImport = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      setStatus(null);
      try {
        const text = await file.text();
        const imported = JSON.parse(text) as LLMConfigItem[];
        if (!Array.isArray(imported)) throw new Error("格式错误：应为配置数组");
        for (const cfg of imported) {
          await api.addLLMConfig({ ...cfg, id: null });
        }
        setStatus(`已导入 ${imported.length} 条配置`);
        await load();
      } catch (err) {
        setStatus(`导入失败：${err instanceof Error ? err.message : err}`);
      } finally {
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    },
    [load],
  );

  const updateEditing = (patch: Partial<LLMConfigItem>) => {
    setEditing((prev) => (prev ? { ...prev, ...patch } : prev));
  };

  if (loading) return <div className="settings-loading">加载中...</div>;
  if (!data) return <div className="settings-empty">无数据</div>;

  const activeConfig = data.configs.find((c) => c.id === data.active_id);

  return (
    <SettingsPageLayout
      title="模型配置"
      description="管理 LLM 配置，支持多配置切换、导入导出与自动故障切换"
      status={status ?? undefined}
    >
      <div className="model-config-grid">
        <SettingsSection
          title="配置列表"
          headerActions={
            <button
              className="settings-btn icon-only"
              onClick={handleNew}
              title="新建配置"
            >
              +
            </button>
          }
        >
          <div className="config-list">
            {data.configs.length === 0 && (
              <div className="settings-empty">暂无配置</div>
            )}
            {data.configs.map((c) => (
              <div
                key={c.id}
                className={`config-list-item ${selectedId === c.id ? "selected" : ""}`}
                onClick={() => selectConfig(c)}
              >
                <span
                  className={`config-active-dot ${data.active_id === c.id ? "" : "inactive"}`}
                  title={data.active_id === c.id ? "当前激活" : "未激活，点击切换连接"}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (c.id && data.active_id !== c.id) handleSetActive(c.id);
                  }}
                />
                <div className="config-list-main">
                  <div className="config-list-title">{c.name || "(未命名)"}</div>
                  <div className="config-list-subtitle">{c.model_name}</div>
                </div>
                {selectedId === c.id && (
                  <span className="config-list-check">✓</span>
                )}
              </div>
            ))}
          </div>

          <div className="page-actions">
            <button className="settings-btn" onClick={handleExport}>
              ↓ 导出配置
            </button>
            <button
              className="settings-btn"
              onClick={() => fileInputRef.current?.click()}
            >
              ↑ 导入配置
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".json"
              style={{ display: "none" }}
              onChange={handleImport}
            />
          </div>
        </SettingsSection>

        {editing ? (
          <SettingsSection
            title="配置参数"
            actions={
              <>
                {editing.id && data.active_id !== editing.id && (
                  <button
                    className="settings-btn"
                    onClick={() => editing.id && handleSetActive(editing.id)}
                    disabled={saving}
                  >
                    激活
                  </button>
                )}
                {editing.id && (
                  <button
                    className="settings-btn danger"
                    onClick={() => editing.id && handleDelete(editing.id)}
                    disabled={saving || data.configs.length <= 1}
                  >
                    删除
                  </button>
                )}
                <button
                  className="settings-btn"
                  onClick={() => {
                    if (selectedId) {
                      const original = data.configs.find((c) => c.id === selectedId);
                      setEditing(original ? { ...original } : null);
                    } else {
                      setEditing(null);
                    }
                  }}
                  disabled={saving}
                >
                  取消
                </button>
                <button
                  className="settings-btn primary"
                  onClick={handleSave}
                  disabled={saving || !editing.name || !editing.model_name}
                >
                  {saving ? "保存中..." : "保存"}
                </button>
              </>
            }
          >
            <div className="model-config-form">
              <SettingsField
                label="配置名称"
                layout="stacked"
                className="model-config-field-half"
              >
                <input
                  className="settings-input"
                  value={editing.name}
                  onChange={(e) => updateEditing({ name: e.target.value })}
                  placeholder="主配置"
                />
              </SettingsField>
              <SettingsField
                label="模型名称"
                layout="stacked"
                className="model-config-field-half"
              >
                <input
                  className="settings-input"
                  value={editing.model_name}
                  onChange={(e) => updateEditing({ model_name: e.target.value })}
                  placeholder="qwen-plus"
                />
              </SettingsField>
              <SettingsField
                label="API Key"
                layout="stacked"
                className="model-config-field-half"
              >
                <div className="input-with-suffix">
                  <input
                    className="settings-input"
                    type={showKey ? "text" : "password"}
                    value={editing.api_key}
                    onChange={(e) => updateEditing({ api_key: e.target.value })}
                    placeholder="sk-..."
                  />
                  <button
                    className="input-suffix-btn"
                    type="button"
                    onClick={() => setShowKey((v) => !v)}
                    title={showKey ? "隐藏" : "显示"}
                  >
                    {showKey ? "🙈" : "👁"}
                  </button>
                </div>
              </SettingsField>
              <SettingsField
                label="Base URL"
                layout="stacked"
                className="model-config-field-half"
              >
                <input
                  className="settings-input"
                  value={editing.base_url}
                  onChange={(e) => updateEditing({ base_url: e.target.value })}
                  placeholder="https://api.example.com/v1"
                />
              </SettingsField>
              <SettingsField
                label="温度系数"
                hint="0-2，值越高越随机"
                layout="stacked"
                className="model-config-field-third"
              >
                <input
                  className="settings-input"
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={editing.temperature}
                  onChange={(e) =>
                    updateEditing({ temperature: parseFloat(e.target.value) || 0 })
                  }
                />
              </SettingsField>
              <SettingsField
                label="Top P"
                hint="0-1，值越小越聚焦"
                layout="stacked"
                className="model-config-field-third"
              >
                <input
                  className="settings-input"
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={editing.top_p}
                  onChange={(e) =>
                    updateEditing({ top_p: parseFloat(e.target.value) || 0 })
                  }
                />
              </SettingsField>
              <SettingsField
                label="频率惩罚"
                hint="值越高越避免重复"
                layout="stacked"
                className="model-config-field-third"
              >
                <input
                  className="settings-input"
                  type="number"
                  step="0.1"
                  value={editing.frequency_penalty}
                  onChange={(e) =>
                    updateEditing({
                      frequency_penalty: parseFloat(e.target.value) || 0,
                    })
                  }
                />
              </SettingsField>
              <div className="model-config-field-half model-config-toggle-cell">
                <Toggle
                  checked={editing.enable_vision}
                  onChange={(checked) => updateEditing({ enable_vision: checked })}
                  label="视觉能力"
                />
              </div>
              <div className="model-config-field-half model-config-toggle-cell">
                <Toggle
                  checked={editing.enable_thinking}
                  onChange={(checked) => updateEditing({ enable_thinking: checked })}
                  label="深度思考能力"
                />
              </div>
            </div>
          </SettingsSection>
        ) : (
          <SettingsSection title="配置参数">
            <div className="settings-empty">请选择或新建配置</div>
          </SettingsSection>
        )}
      </div>

      <SettingsSection title="自动故障切换">
        <Toggle
          checked={data.auto_switch_on_failure}
          onChange={async (checked) => {
            try {
              await api.setConfig(
                "LLM_AUTO_SWITCH_ON_FAILURE",
                String(checked),
              );
              setData({ ...data, auto_switch_on_failure: checked });
              setStatus("自动故障切换已更新");
            } catch (err) {
              setStatus(
                `更新失败：${err instanceof APIError ? err.detail : err}`,
              );
            }
          }}
          label="启用自动故障切换（当当前配置失败时自动切换到下一组）"
        />
      </SettingsSection>

      <div className="page-status">
        当前激活配置: {activeConfig ? `${activeConfig.name} (${activeConfig.model_name})` : "无"}
      </div>
    </SettingsPageLayout>
  );
}
