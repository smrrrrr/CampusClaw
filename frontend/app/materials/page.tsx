"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AuthGate } from "@/components/auth-guard";
import { ClassSelector } from "@/components/class-selector";
import { LogoutButton } from "@/components/logout-button";
import { SwitchChildButton } from "@/components/switch-child";
import { MaterialPreview } from "@/components/material-preview";
import { api, ApiError, MaterialItemDTO } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

function MaterialsHome() {
  const userRole = useAuthStore((s) => s.userRole);
  const teachingClasses = useAuthStore((s) => s.teachingClasses);
  const currentStudent = useAuthStore((s) => s.currentStudent);
  const [classFilter, setClassFilter] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<MaterialItemDTO[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [previewItem, setPreviewItem] = useState<MaterialItemDTO | null>(null);

  const isTeacher = userRole === "teacher";
  const hasClasses = isTeacher
    ? teachingClasses != null && teachingClasses.length > 0
    : currentStudent?.class_id != null;

  // 教师默认选第一个任教班级
  useEffect(() => {
    if (isTeacher && classFilter === null && teachingClasses && teachingClasses.length > 0) {
      setClassFilter(teachingClasses[0]);
    }
  }, [isTeacher, classFilter, teachingClasses]);

  const fetchMaterials = async (cid: number | null, searchStr: string) => {
    if (cid === null) return;
    setLoading(true);
    setError("");
    try {
      const data = await api.listMaterials({ class_id: cid || undefined, search: searchStr || undefined });
      setItems(data.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载材料列表失败");
      setItems([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isTeacher && currentStudent?.class_id != null) {
      fetchMaterials(currentStudent.class_id, search);
    }
  }, [isTeacher, currentStudent?.class_id]);

  useEffect(() => {
    if (isTeacher && classFilter !== null) {
      fetchMaterials(classFilter, search);
    }
  }, [isTeacher, classFilter]);

  const handleSearch = () => {
    const cid = isTeacher ? classFilter : currentStudent?.class_id ?? null;
    fetchMaterials(cid, search);
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / 1024 / 1024).toFixed(2)}MB`;
  };

  const isImage = (mime: string) => mime.startsWith("image/");
  const isPdf = (mime: string) => mime === "application/pdf";

  const downloadFile = (item: MaterialItemDTO) => {
    const token = useAuthStore.getState().accessToken;
    const url = api.materialDownloadUrl(item.id);
    fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
      credentials: "include",
    })
      .then((res) => {
        if (!res.ok) throw new Error("下载失败");
        return res.blob();
      })
      .then((blob) => {
        const objUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = objUrl;
        a.download = item.filename;
        a.click();
        URL.revokeObjectURL(objUrl);
      })
      .catch((err) => setError(err.message || "下载失败"));
  };

  const handleDelete = async (item: MaterialItemDTO) => {
    if (!window.confirm(`确定删除「${item.filename}」吗？删除后将无法恢复。`)) return;
    setDeletingId(item.id);
    setError("");
    try {
      await api.deleteMaterial(item.id);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
      if (previewItem?.id === item.id) setPreviewItem(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <>
      <div className="topbar">
        <strong className="brand">CampusClaw {isTeacher ? "教师端" : "学生端"}</strong>
        <div className="actions">
          {isTeacher ? (
            <>
              <Link href="/teacher" className="btn" style={{ width: "auto", padding: "8px 16px", textDecoration: "none" }}>
                工作台
              </Link>
              <Link href="/teacher/upload" className="btn" style={{ width: "auto", padding: "8px 16px", textDecoration: "none" }}>
                上传资料
              </Link>
            </>
          ) : (
            <>
              <Link href="/student" className="btn" style={{ width: "auto", padding: "8px 16px", textDecoration: "none" }}>
                首页
              </Link>
              <SwitchChildButton />
            </>
          )}
          <LogoutButton />
        </div>
      </div>
      <div className="content">
        <h2 style={{ marginBottom: 16 }}>学习资料</h2>

        {!hasClasses ? (
          <div className="card" style={{ textAlign: "center", padding: 32 }}>
            <p className="hint" style={{ fontSize: 16 }}>
              {isTeacher ? "暂无任教班级" : "暂无班级"}
            </p>
            <p className="hint" style={{ marginTop: 8 }}>
              {isTeacher ? "您尚未被分配任教班级，请联系管理员处理。" : "您尚未被分配到任何班级，请联系教师或管理员处理。"}
            </p>
          </div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
              {isTeacher && (
                <>
                  <label className="hint">选择班级：</label>
                  <ClassSelector value={classFilter} onChange={setClassFilter} />
                </>
              )}
              <input
                className="input"
                style={{ flex: 1 }}
                placeholder="搜索描述或标签…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              />
              <button className="btn" style={{ width: "auto", padding: "8px 16px" }} onClick={handleSearch} disabled={loading}>
                搜索
              </button>
            </div>

            {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}

            {loading ? (
              <p className="hint">加载中…</p>
            ) : items.length === 0 ? (
              <p className="hint">暂无资料</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "2px solid #e5e7eb" }}>
                    <th style={{ padding: "8px 4px" }}>文件名</th>
                    <th style={{ padding: "8px 4px" }}>班级</th>
                    <th style={{ padding: "8px 4px" }}>大小</th>
                    <th style={{ padding: "8px 4px" }}>描述</th>
                    <th style={{ padding: "8px 4px" }}>标签</th>
                    <th style={{ padding: "8px 4px" }}>索引</th>
                    <th style={{ padding: "8px 4px" }}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "8px 4px" }}>{item.filename}</td>
                      <td style={{ padding: "8px 4px" }}>{item.class_name ?? item.class_id}</td>
                      <td style={{ padding: "8px 4px" }}>{formatSize(item.file_size)}</td>
                      <td style={{ padding: "8px 4px" }}>{item.description ?? "—"}</td>
                      <td style={{ padding: "8px 4px" }}>
                        {item.tags.length > 0 ? item.tags.join(", ") : "—"}
                      </td>
                      <td style={{ padding: "8px 4px" }}>
                        {item.is_indexed ? (
                          <span style={{ color: "#059669" }}>已索引</span>
                        ) : (
                          <span style={{ color: "#9ca3af" }}>未索引</span>
                        )}
                      </td>
                      <td style={{ padding: "8px 4px", whiteSpace: "nowrap" }}>
                        {(isPdf(item.file_type) || isImage(item.file_type)) && (
                          <button
                            className="btn"
                            style={{ width: "auto", padding: "4px 10px", fontSize: 13, marginRight: 4 }}
                            onClick={() => setPreviewItem(item)}
                          >
                            预览
                          </button>
                        )}
                        <button
                          className="btn"
                          style={{ width: "auto", padding: "4px 10px", fontSize: 13 }}
                          onClick={() => downloadFile(item)}
                        >
                          下载
                        </button>
                        {isTeacher && (
                          <button
                            className="btn"
                            style={{
                              width: "auto",
                              padding: "4px 10px",
                              fontSize: 13,
                              marginLeft: 4,
                              color: "#dc2626",
                              borderColor: "#fecaca",
                            }}
                            onClick={() => handleDelete(item)}
                            disabled={deletingId === item.id}
                          >
                            {deletingId === item.id ? "删除中…" : "删除"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>

      {previewItem && (
        <MaterialPreview
          item={previewItem}
          onClose={() => setPreviewItem(null)}
        />
      )}
    </>
  );
}

export default function MaterialsPage() {
  return (
    <AuthGate>
      <MaterialsHome />
    </AuthGate>
  );
}
