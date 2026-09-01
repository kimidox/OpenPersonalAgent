import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./MarkdownRenderer.css";

interface Props {
  content: string;
}

/** 合并模型输出中的连续空行，避免 2+ 个空行被渲染成过大的块级间距 */
function normalizeBlankLines(text: string): string {
  return text.replace(/\n{3,}/g, "\n\n");
}

/** 把松散列表转为紧凑列表：删除列表项之间的空行，避免 <li> 被包进 <p>。
 *  仅处理以 -、*、+、数字. 开头的列表项之间的空行，保留段落结构。
 */
function compactLists(text: string): string {
  return text
    // 删除同层级列表项之间的空行（- / * / + 开头）
    .replace(/^(\s*)[-*+][ \t]+.*\n\n(?=\s*[-*+][ \t])/gm, (m) => m.replace("\n\n", "\n"))
    // 删除有序列表项之间的空行（数字. 开头）
    .replace(/^(\s*)\d+\.[ \t]+.*\n\n(?=\s*\d+\.[ \t])/gm, (m) => m.replace("\n\n", "\n"));
}

export default function MarkdownRenderer({ content }: Props) {
  const normalized = compactLists(normalizeBlankLines(content));
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // 链接新窗口打开
          a: ({ node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
          // 代码块
          pre: ({ node, ...props }) => <pre className="md-pre" {...props} />,
          code: ({ node, className, children, ...props }) => {
            const isInline = !className && !String(children).includes("\n");
            return isInline ? (
              <code className="md-code-inline" {...props}>{children}</code>
            ) : (
              <code className={className} {...props}>{children}</code>
            );
          },
        }}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
