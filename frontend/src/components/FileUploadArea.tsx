import { useRef, useState } from "react";
import { api, APIError } from "@/api/client";
import "./FileUploadArea.css";

interface Props {
  onUploaded: (summary: string) => void;
  disabled?: boolean;
}

export default function FileUploadArea({ onUploaded, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      const data = await api.uploadFile(file);
      // 把解析文本注入 SkillAgent，供下一次 run 使用
      await api.setUploadedContent(data.parsed_text);
      const summary =
        data.parsed_pages > 0
          ? `📎 ${data.original_name}（${data.parsed_pages} 页）`
          : `📎 ${data.original_name}`;
      onUploaded(summary);
    } catch (err) {
      const msg = err instanceof APIError || err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setUploading(false);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    if (disabled || uploading) return;
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  return (
    <div
      className="file-upload-area"
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
    >
      <input
        ref={inputRef}
        type="file"
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleFile(f);
          e.target.value = "";
        }}
        disabled={disabled || uploading}
      />
      <button
        type="button"
        className="upload-btn"
        onClick={() => inputRef.current?.click()}
        disabled={disabled || uploading}
      >
        {uploading ? "上传中..." : "📎 附件"}
      </button>
      {error && <span className="upload-error">{error}</span>}
    </div>
  );
}
