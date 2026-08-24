/**
 * 文件标签工具：在用户 query 中以 XML 标签嵌入文件内容。
 *
 * 格式：
 * <Files>
 *   <File>
 *     <filename>文件名</filename>
 *     <content>文件解析后的文本内容</content>
 *   </File>
 * </Files>
 *
 * - 发送给 LLM 时，标签内包含完整文件内容，模型可直接阅读。
 * - 前端渲染时，剥离 <Files> 块，只显示用户原生 query + 文件卡片。
 */

import type { FileAttachment } from "@/types/api";

export interface ParsedFileEntry {
  filename: string;
  content: string;
}

export interface ParsedQuery {
  /** 剥离 <Files> 标签后的纯用户文本 */
  text: string;
  /** 从标签中解析出的文件列表 */
  files: ParsedFileEntry[];
}

/**
 * 对字符串进行 XML 转义，防止文件内容中的 < > & 破坏标签结构。
 */
function escapeXml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/**
 * 对 XML 转义字符串进行反转义。
 */
function unescapeXml(str: string): string {
  return str
    .replace(/&gt;/g, ">")
    .replace(/&lt;/g, "<")
    .replace(/&amp;/g, "&");
}

/**
 * 将用户原始 query 和文件附件列表组装成带 <Files> 标签的完整 query。
 *
 * @param query 用户输入的原始文本
 * @param attachments 上传的文件附件列表
 * @returns 拼接后的完整 query（含文件标签）
 */
export function buildQueryWithFiles(
  query: string,
  attachments?: FileAttachment[] | null,
): string {
  if (!attachments || attachments.length === 0) {
    return query;
  }

  const fileBlocks = attachments
    .map((a) => {
      const content = a.parsed_text || `（文件 ${a.original_name} 无解析内容）`;
      return `  <File>\n    <filename>${escapeXml(a.original_name)}</filename>\n    <content>${escapeXml(content)}</content>\n  </File>`;
    })
    .join("\n");

  return `${query}\n<Files>\n${fileBlocks}\n</Files>`;
}

/**
 * 从完整 query 中解析出用户原生文本和文件列表。
 *
 * @param fullQuery 可能包含 <Files> 标签的完整 query
 * @returns { text, files }
 */
export function parseQueryFiles(fullQuery: string): ParsedQuery {
  const filesBlockRegex = /<Files>([\s\S]*?)<\/Files>/;
  const match = fullQuery.match(filesBlockRegex);
  if (!match) {
    return { text: fullQuery, files: [] };
  }

  // 剥离 <Files> 块及其前后的多余空白
  const text = fullQuery.replace(filesBlockRegex, "").trimEnd();

  // 解析 <File> 条目
  const files: ParsedFileEntry[] = [];
  const fileRegex = /<File>\s*<filename>([\s\S]*?)<\/filename>\s*<content>([\s\S]*?)<\/content>\s*<\/File>/g;
  let fileMatch: RegExpExecArray | null;
  while ((fileMatch = fileRegex.exec(match[1])) !== null) {
    files.push({
      filename: unescapeXml(fileMatch[1].trim()),
      content: unescapeXml(fileMatch[2].trim()),
    });
  }

  return { text, files };
}
