import { useRef, useState } from "react";
import { api, APIError } from "@/api/client";
import type { FileAttachment } from "@/types/api";
import "./FileUploadArea.css";

interface Props {
  onUploaded: (attachment: FileAttachment) => void;
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
      // 注意：不再调用 api.setUploadedContent()，也不回传 parsed_text。
      // 上传即持久化（manifest + sidecar），发送时由后端按 query 中
      // <File:fid/> 占位符懒加载注入，避免内容残留在 SkillAgent 单例。
      const summary =
        data.parsed_pages > 0
          ? `📎 ${data.original_name}（${data.parsed_pages} 页）`
          : `📎 ${data.original_name}`;
      const attachment: FileAttachment = {
        file_id: data.file_id,
        original_name: data.original_name,
        file_size: data.file_size,
        mime_type: data.mime_type,
        parsed_pages: data.parsed_pages,
        summary,
        parsed_text: data.parsed_text,
      };
      onUploaded(attachment);
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
