"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import type { MaterialItemDTO } from "@/lib/api";

/**
 * 在线预览组件：
 * - PDF → iframe 渲染 blob URL
 * - 图片（JPG/PNG）→ img 渲染 blob URL
 * 鉴权：通过 Authorization 头获取文件流，转为 blob URL 展示。
 */
export function MaterialPreview({
  item,
  onClose,
}: {
  item: MaterialItemDTO;
  onClose: () => void;
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = useAuthStore.getState().accessToken;
    const url = api.materialPreviewUrl(item.id);
    setLoading(true);
    fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
      credentials: "include",
    })
      .then((res) => {
        if (!res.ok) throw new Error(res.status === 403 ? "无权预览该材料" : "预览加载失败");
        return res.blob();
      })
      .then((blob) => {
        setBlobUrl(URL.createObjectURL(blob));
        setError("");
      })
      .catch((err) => setError(err.message || "预览加载失败"))
      .finally(() => setLoading(false));

    return () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  const isImage = item.file_type.startsWith("image/");

  return (
    <div
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: "rgba(0,0,0,0.6)",
        display: "flex",
        flexDirection: "column",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "#fff",
          margin: "40px auto",
          borderRadius: 12,
          width: "90%",
          maxWidth: 1000,
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "12px 16px",
            borderBottom: "1px solid #e5e7eb",
          }}
        >
          <strong style={{ fontSize: 14 }}>{item.filename}</strong>
          <button className="btn" style={{ width: "auto", padding: "4px 12px", fontSize: 13 }} onClick={onClose}>
            关闭
          </button>
        </div>
        <div style={{ flex: 1, overflow: "auto", display: "flex", justifyContent: "center", alignItems: "center" }}>
          {loading && <p className="hint">加载中…</p>}
          {error && <p className="error">{error}</p>}
          {blobUrl && !error && (
            isImage ? (
              <img src={blobUrl} alt={item.filename} style={{ maxWidth: "100%", maxHeight: "80vh" }} />
            ) : (
              <iframe src={blobUrl} style={{ width: "100%", height: "75vh", border: "none" }} title={item.filename} />
            )
          )}
        </div>
      </div>
    </div>
  );
}
