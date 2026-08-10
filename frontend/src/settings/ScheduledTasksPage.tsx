import { useCallback, useEffect, useState } from "react";
import { api, APIError } from "@/api/client";
import type {
  AutostartResponse,
  ScheduledTaskCreate,
  ScheduledTaskResponse,
} from "@/types/api";
import Modal from "@/components/Modal";
import { SettingsField, SettingsPageLayout, SettingsSection } from "./SettingsSection";
import Toggle from "./Toggle";

interface TaskForm {
  title: string;
  content: string;
  triggerDate: string;
  triggerTime: string;
  repeatType: string;
  notificationType: string;
  executionType: string;
}

interface EditingState {
  mode: "create" | "edit";
  taskId: string | null;
  form: TaskForm;
}

const EMPTY_FORM: TaskForm = {
  title: "",
  content: "",
  triggerDate: "",
  triggerTime: "",
  repeatType: "none",
  notificationType: "system",
  executionType: "notification",
};

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待触发" },
  { value: "triggered", label: "已触发" },
  { value: "cancelled", label: "已取消" },
];

const REPEAT_TYPES: { value: string; label: string }[] = [
  { value: "none", label: "不重复" },
  { value: "daily", label: "每日" },
  { value: "weekly", label: "每周" },
  { value: "monthly", label: "每月" },
];

const NOTIFICATION_TYPES: { value: string; label: string }[] = [
  { value: "system", label: "系统通知" },
  { value: "toast", label: "Toast" },
];

const EXECUTION_TYPES: { value: string; label: string }[] = [
  { value: "notification", label: "通知" },
  { value: "agent_conversation", label: "智能体会话" },
];

function splitIso(iso: string): { date: string; time: string } {
  if (!iso) return { date: "", time: "" };
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { date: "", time: "" };
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const time = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return { date, time };
}

function mergeIso(date: string, time: string): string {
  if (!date || !time) return new Date().toISOString();
  const d = new Date(`${date}T${time}:00`);
  return d.toISOString();
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}...` : s;
}

export default function ScheduledTasksPage() {
  const [tasks, setTasks] = useState<ScheduledTaskResponse[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [autostart, setAutostart] = useState<AutostartResponse | null>(null);
  const [editing, setEditing] = useState<EditingState | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const loadTasks = useCallback(async (statusFilter: string) => {
    try {
      const resp = await api.listScheduledTasks(
        statusFilter === "all" ? undefined : statusFilter,
      );
      setTasks(resp);
    } catch (err) {
      setStatus(`加载失败：${err instanceof APIError ? err.detail : err}`);
    }
  }, []);

  const loadAutostart = useCallback(async () => {
    try {
      const resp = await api.getAutostart();
      setAutostart(resp);
    } catch (err) {
      setStatus(`自启状态加载失败：${err instanceof APIError ? err.detail : err}`);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadTasks(filter), loadAutostart()]).finally(() =>
      setLoading(false),
    );
  }, [filter, loadTasks, loadAutostart]);

  const openCreate = () => {
    setEditing({ mode: "create", taskId: null, form: { ...EMPTY_FORM } });
  };

  const openEdit = (task: ScheduledTaskResponse) => {
    const { date, time } = splitIso(task.trigger_time);
    setEditing({
      mode: "edit",
      taskId: task.task_id,
      form: {
        title: task.title,
        content: task.content,
        triggerDate: date,
        triggerTime: time,
        repeatType: task.repeat_type || "none",
        notificationType: task.notification_type || "system",
        executionType: task.execution_type || "notification",
      },
    });
  };

  const updateForm = (patch: Partial<TaskForm>) => {
    setEditing((prev) =>
      prev ? { ...prev, form: { ...prev.form, ...patch } } : prev,
    );
  };

  const handleSave = useCallback(async () => {
    if (!editing) return;
    if (!editing.form.title.trim()) {
      setStatus("请填写任务标题");
      return;
    }
    setSaving(true);
    setStatus(null);
    const triggerTime = mergeIso(
      editing.form.triggerDate,
      editing.form.triggerTime,
    );
    const body: ScheduledTaskCreate = {
      title: editing.form.title,
      content: editing.form.content,
      trigger_time: triggerTime,
      repeat_type: editing.form.repeatType,
      notification_type: editing.form.notificationType,
      execution_type: editing.form.executionType,
    };
    try {
      if (editing.mode === "create") {
        await api.createScheduledTask(body);
        setStatus("任务已创建");
      } else if (editing.taskId) {
        await api.updateScheduledTask(editing.taskId, body);
        setStatus("任务已更新");
      }
      setEditing(null);
      await loadTasks(filter);
    } catch (err) {
      setStatus(`保存失败：${err instanceof APIError ? err.detail : err}`);
    } finally {
      setSaving(false);
    }
  }, [editing, filter, loadTasks]);

  const handleDelete = useCallback(
    async (taskId: string) => {
      if (!confirm("确认删除该任务？")) return;
      try {
        await api.deleteScheduledTask(taskId);
        setStatus("任务已删除");
        await loadTasks(filter);
      } catch (err) {
        setStatus(`删除失败：${err instanceof APIError ? err.detail : err}`);
      }
    },
    [filter, loadTasks],
  );

  const handleAutostartToggle = useCallback(async (enabled: boolean) => {
    try {
      const resp = enabled
        ? await api.enableAutostart()
        : await api.disableAutostart();
      setAutostart(resp);
      setStatus(enabled ? "已启用开机自启" : "已禁用开机自启");
    } catch (err) {
      setStatus(`更新失败：${err instanceof APIError ? err.detail : err}`);
    }
  }, []);

  if (loading) return <div className="settings-loading">加载中...</div>;

  return (
    <SettingsPageLayout
      title="定时任务管理"
      description="创建和管理定时触发的任务，支持发送通知或启动 Agent 对话。"
      status={status ?? undefined}
    >
      <SettingsSection title="任务列表">
        <div className="section-toolbar">
          <button className="settings-btn primary" onClick={openCreate}>
            + 新建任务
          </button>
          <div className="toolbar-group">
            <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>筛选：</span>
            <select
              className="settings-select"
              style={{ width: "auto", minWidth: 120 }}
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              {STATUS_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="settings-list">
          {tasks.length === 0 && <div className="settings-empty">暂无任务</div>}
          {tasks.map((t) => (
            <div key={t.task_id} className="settings-list-item">
              <div className="list-item-main">
                <div className="list-item-title">
                  {t.title || "(未命名任务)"}
                  <span
                    className={`settings-tag ${t.status === "triggered" ? "success" : "info"}`}
                  >
                    {t.status}
                  </span>
                </div>
                <div className="list-item-meta">
                  {truncate(t.content, 60) || "(无内容)"} · 触发：{t.trigger_time}{" "}
                  · 重复：{t.repeat_type} · 执行：{t.execution_type}
                </div>
              </div>
              <div className="list-item-actions">
                <button className="settings-btn" onClick={() => openEdit(t)}>
                  编辑
                </button>
                <button
                  className="settings-btn danger"
                  onClick={() => handleDelete(t.task_id)}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      </SettingsSection>

      <SettingsSection title="启动设置">
        <Toggle
          checked={autostart?.enabled ?? false}
          onChange={handleAutostartToggle}
          label="开机自动启动"
        />
        <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: -8 }}>
          {autostart?.enabled ? "已启用" : "未启用"}
        </div>
      </SettingsSection>

      <div className="page-status">共 {tasks.length} 个任务</div>

      <Modal
        title={editing?.mode === "create" ? "新建任务" : "编辑任务"}
        open={!!editing}
        onClose={() => setEditing(null)}
        footer={
          <>
            <button
              className="settings-btn"
              onClick={() => setEditing(null)}
              disabled={saving}
            >
              取消
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
        {editing && (
          <>
            <SettingsField label="任务标题" layout="stacked">
              <input
                className="settings-input"
                value={editing.form.title}
                onChange={(e) => updateForm({ title: e.target.value })}
                placeholder="任务标题"
              />
            </SettingsField>
            <SettingsField label="任务内容" layout="stacked">
              <textarea
                className="settings-textarea"
                value={editing.form.content}
                onChange={(e) => updateForm({ content: e.target.value })}
                placeholder="任务内容"
              />
            </SettingsField>
            <SettingsField label="触发日期" layout="stacked">
              <input
                className="settings-input"
                type="date"
                value={editing.form.triggerDate}
                onChange={(e) => updateForm({ triggerDate: e.target.value })}
              />
            </SettingsField>
            <SettingsField label="触发时间" layout="stacked">
              <input
                className="settings-input"
                type="time"
                value={editing.form.triggerTime}
                onChange={(e) => updateForm({ triggerTime: e.target.value })}
              />
            </SettingsField>
            <SettingsField label="重复类型" layout="stacked">
              <select
                className="settings-select"
                value={editing.form.repeatType}
                onChange={(e) => updateForm({ repeatType: e.target.value })}
              >
                {REPEAT_TYPES.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </SettingsField>
            <SettingsField label="通知类型" layout="stacked">
              <select
                className="settings-select"
                value={editing.form.notificationType}
                onChange={(e) =>
                  updateForm({ notificationType: e.target.value })
                }
              >
                {NOTIFICATION_TYPES.map((n) => (
                  <option key={n.value} value={n.value}>
                    {n.label}
                  </option>
                ))}
              </select>
            </SettingsField>
            <SettingsField label="执行方式" layout="stacked">
              <select
                className="settings-select"
                value={editing.form.executionType}
                onChange={(e) => updateForm({ executionType: e.target.value })}
              >
                {EXECUTION_TYPES.map((ex) => (
                  <option key={ex.value} value={ex.value}>
                    {ex.label}
                  </option>
                ))}
              </select>
            </SettingsField>
          </>
        )}
      </Modal>
    </SettingsPageLayout>
  );
}
