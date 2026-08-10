/**
 * 通用设置页组件：标题 + 说明 + 分区卡片 + 字段行。
 *
 * 复刻 ui_flet/settings 的共性 UI 模式（调研报告第 6 节）：
 * - 标题(Text 14 粗体) + 说明(Text 10 灰)
 * - 分区卡片（surface + 圆角 + 边框）
 * - 底部状态栏
 */
import type { ReactNode } from "react";
import "./Settings.css";

interface SettingsSectionProps {
  title: string;
  description?: string;
  children: ReactNode;
  actions?: ReactNode;
  headerActions?: ReactNode;
}

export function SettingsSection({
  title,
  description,
  children,
  actions,
  headerActions,
}: SettingsSectionProps) {
  return (
    <section className="settings-section">
      <div className="section-header">
        <div>
          <h3 className="section-title">{title}</h3>
          {description && <p className="section-desc">{description}</p>}
        </div>
        {headerActions && (
          <div className="section-header-actions">{headerActions}</div>
        )}
      </div>
      <div className="section-body">{children}</div>
      {actions && <div className="section-actions">{actions}</div>}
    </section>
  );
}

interface SettingsFieldProps {
  label: string;
  hint?: string;
  children: ReactNode;
  layout?: "row" | "stacked";
  className?: string;
}

export function SettingsField({
  label,
  hint,
  children,
  layout = "row",
  className,
}: SettingsFieldProps) {
  return (
    <div className={`settings-field settings-field--${layout} ${className ?? ""}`}>
      <div className="field-label">
        <span className="field-name">{label}</span>
        {hint && <span className="field-hint">{hint}</span>}
      </div>
      <div className="field-control">{children}</div>
    </div>
  );
}

interface SettingsPageLayoutProps {
  title: string;
  description?: string;
  children: ReactNode;
  status?: string | null;
}

export function SettingsPageLayout({
  title,
  description,
  children,
  status,
}: SettingsPageLayoutProps) {
  return (
    <div className="settings-page-layout">
      <header className="page-header">
        <h2 className="page-title">{title}</h2>
        {description && <p className="page-desc">{description}</p>}
      </header>
      <div className="page-content">{children}</div>
      {status && <footer className="page-status">{status}</footer>}
    </div>
  );
}
