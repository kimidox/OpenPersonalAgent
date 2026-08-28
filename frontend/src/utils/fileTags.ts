/**
 * 用户 query 中的引用占位符工具。
 *
 * 占位符语法（与后端 SkillAgent._REF_TAG_RE 对齐）：
 *   <Skill:id/>   强制引用 Skill
 *   <File:fid/>   强制引用上传文件（fid 为 /api/files/upload 返回的 file_id）
 *   <Cli:name/>   强制引用 CLI 工具
 *
 * - 发送时：附件以占位符追加在 query 尾部；文件内容不回传（后端持久层懒加载）
 * - 渲染时：剥离占位符，结合 metadata.forced_refs 渲染引用 chip / 文件卡片
 */

import type { FileAttachment } from "@/types/api";

/** 占位符正则（与后端 _REF_TAG_RE 保持一致） */
export const REF_TAG_RE = /<(Skill|File|Cli):([A-Za-z0-9_-]+)\/>/g;

export interface RefTagInfo {
  kind: "Skill" | "File" | "Cli";
  id: string;
}

/** 从文本中提取占位符引用（去重保序） */
export function extractRefTags(text: string): RefTagInfo[] {
  const refs: RefTagInfo[] = [];
  const seen = new Set<string>();
  REF_TAG_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = REF_TAG_RE.exec(text)) !== null) {
    const key = `${m[1]}:${m[2]}`;
    if (!seen.has(key)) {
      seen.add(key);
      refs.push({ kind: m[1] as RefTagInfo["kind"], id: m[2] });
    }
  }
  return refs;
}

/** 剥离占位符后的纯文本 */
export function stripRefTags(text: string): string {
  return text
    .replace(REF_TAG_RE, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** 将用户原始 query 与附件列表组装为带占位符的完整 query */
export function buildQueryWithFileRefs(
  query: string,
  attachments?: FileAttachment[] | null,
): string {
  if (!attachments || attachments.length === 0) {
    return query;
  }
  const tags = attachments.map((a) => `<File:${a.file_id}/>`).join(" ");
  return `${query}\n${tags}`.trim();
}

/** 本地回显用的 forced_refs 元数据（与后端 ext.forced_refs 同构） */
export function buildLocalForcedRefs(
  attachments?: FileAttachment[] | null,
): { forced_refs: { type: string; id: string; file_name: string }[] } | null {
  if (!attachments || attachments.length === 0) return null;
  return {
    forced_refs: attachments.map((a) => ({
      type: "file",
      id: a.file_id,
      file_name: a.original_name,
    })),
  };
}
