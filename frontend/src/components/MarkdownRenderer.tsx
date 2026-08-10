import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./MarkdownRenderer.css";

interface Props {
  content: string;
}

export default function MarkdownRenderer({ content }: Props) {
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
        {content}
      </ReactMarkdown>
    </div>
  );
}
