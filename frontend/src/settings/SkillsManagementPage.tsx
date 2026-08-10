/**
 * 用户自定义 Skill 管理页：列表 / 搜索 / 导入 / 删除。
 *
 * 对应 ui_flet/settings/skills_management_page.py。
 * 端点：GET /api/skills，POST /api/skills/install，DELETE /api/skills/{id}
 *
 * Skill 发布仅通过「导入」上传 .md 或 .zip（后端未暴露创建空 Skill 的端点）。
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import { api, APIError } from "@/api/client";
import type { SkillSummary } from "@/types/api";
import { SettingsField, SettingsPageLayout, SettingsSection } from "./SettingsSection";

export default function SkillsManagementPage() {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.listSkills();
      setSkills(resp);
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

  const handleImportClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    async (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      setStatus(null);
      setImporting(true);
      try {
        const resp = await api.installSkill(file);
        setStatus(`导入成功：${resp.message}`);
        await load();
      } catch (err) {
        setStatus(`导入失败：${err instanceof APIError ? err.detail : err}`);
      } finally {
        setImporting(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    },
    [load],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm("确认删除该 Skill？")) return;
      setStatus(null);
      try {
        await api.deleteSkill(id);
        setStatus("Skill 已删除");
        await load();
      } catch (err) {
        setStatus(`删除失败：${err instanceof APIError ? err.detail : err}`);
      }
    },
    [load],
  );

  const handleSearch = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    setQuery(e.target.value);
  }, []);

  const filtered = skills.filter((s) => {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (
      s.name.toLowerCase().includes(q) ||
      s.description.toLowerCase().includes(q)
    );
  });

  return (
    <SettingsPageLayout
      title="用户自定义 Skill 管理"
      description="导入、搜索与删除 Skill（.md 或 .zip）"
      status={status ?? undefined}
    >
      <SettingsSection
        title="Skill 列表"
        headerActions={
          <>
            <button
              className="settings-btn primary"
              onClick={handleImportClick}
              disabled={importing}
            >
              {importing ? "导入中..." : "导入 Skill"}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.zip"
              style={{ display: "none" }}
              onChange={handleFileChange}
            />
          </>
        }
      >
        <SettingsField label="搜索" hint="按名称或描述模糊匹配">
          <input
            className="settings-input"
            value={query}
            onChange={handleSearch}
            placeholder="输入关键字..."
          />
        </SettingsField>

        {loading ? (
          <div className="settings-loading">加载中...</div>
        ) : filtered.length === 0 ? (
          <div className="settings-empty">
            {skills.length === 0
              ? "暂无 Skill，点击「导入」添加"
              : "无匹配结果"}
          </div>
        ) : (
          <div className="settings-list">
            {filtered.map((s) => (
              <div key={s.id} className="settings-list-item">
                <div className="list-item-main">
                  <div className="list-item-title">
                    {s.name || "(未命名)"}
                    <span
                      className={`settings-status ${s.is_builtin ? "info" : "success"}`}
                      style={{ marginLeft: 8 }}
                    >
                      {s.is_builtin ? "内置" : "用户"}
                    </span>
                    {s.is_disabled && (
                      <span
                        className="settings-status error"
                        style={{ marginLeft: 8 }}
                      >
                        已禁用
                      </span>
                    )}
                  </div>
                  <div className="list-item-meta">
                    {s.description || "(无描述)"} · ID: {s.id}
                  </div>
                </div>
                <div className="list-item-actions">
                  <button
                    className="settings-btn danger"
                    onClick={() => handleDelete(s.id)}
                    disabled={s.is_builtin}
                    title={s.is_builtin ? "内置 Skill 不可删除" : "删除该 Skill"}
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </SettingsSection>
    </SettingsPageLayout>
  );
}
