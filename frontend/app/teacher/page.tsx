"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AuthGate } from "@/components/auth-guard";
import { ClassSelector } from "@/components/class-selector";
import { LogoutButton } from "@/components/logout-button";
import { api, ApiError } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

interface StudentRow {
  id: number;
  identifier: string;
  name: string | null;
  class_id: number | null;
  class_name: string | null;
  phone: string | null;
}

function TeacherHome() {
  const teachingClasses = useAuthStore((s) => s.teachingClasses);
  const [classId, setClassId] = useState<number | null>(null);
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [loadingStudents, setLoadingStudents] = useState(false);
  const [error, setError] = useState("");

  const hasClasses = teachingClasses != null && teachingClasses.length > 0;

  // 默认选第一个任教班级
  useEffect(() => {
    if (classId === null && hasClasses) {
      setClassId(teachingClasses![0]);
    }
  }, [teachingClasses, classId, hasClasses]);

  // 拉取学生列表（API 请求不携带 class_id，后端从 JWT teaching_classes 过滤）
  useEffect(() => {
    if (classId === null) return;
    setLoadingStudents(true);
    setError("");
    api
      .listStudents()
      .then((data) => {
        setStudents(
          data.items.map((s) => ({
            id: s.id,
            identifier: s.identifier,
            name: s.name,
            class_id: s.class_id,
            class_name: s.class_name,
            phone: s.phone,
          })),
        );
      })
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "加载学生列表失败");
      })
      .finally(() => setLoadingStudents(false));
  }, [classId]);

  // 前端班级渲染控制：仅渲染选中班级的学生（不在 API 请求中暴露 class_id）
  const filteredStudents =
    classId !== null
      ? students.filter((s) => s.class_id === classId)
      : students;

  return (
    <>
      <div className="topbar">
        <strong>CampusClaw 教师端</strong>
        <div className="actions">
          <Link href="/teacher/upload" className="btn" style={{ width: "auto", padding: "8px 16px", textDecoration: "none" }}>
            上传资料
          </Link>
          <Link href="/materials" className="btn" style={{ width: "auto", padding: "8px 16px", textDecoration: "none" }}>
            学习资料
          </Link>
          <LogoutButton />
        </div>
      </div>
      <div className="content">
        <h2 style={{ marginBottom: 12 }}>教师工作台</h2>

        {!hasClasses ? (
          <div className="card" style={{ textAlign: "center", padding: 32 }}>
            <p className="hint" style={{ fontSize: 16 }}>
              暂无任教班级
            </p>
            <p className="hint" style={{ marginTop: 8 }}>
              您尚未被分配任教班级，请联系管理员处理。
            </p>
          </div>
        ) : (
          <>
            <div style={{ marginBottom: 16 }}>
              <label className="hint" style={{ marginRight: 8 }}>
                选择班级：
              </label>
              <ClassSelector value={classId} onChange={setClassId} />
            </div>

            <h3 style={{ marginBottom: 8 }}>本班学生</h3>
            {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}
            {loadingStudents ? (
              <p className="hint">加载中…</p>
            ) : filteredStudents.length === 0 ? (
              <p className="hint">暂无学生</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
                <thead>
                  <tr style={{ textAlign: "left", borderBottom: "2px solid #e5e7eb" }}>
                    <th style={{ padding: "8px 4px" }}>学号</th>
                    <th style={{ padding: "8px 4px" }}>姓名</th>
                    <th style={{ padding: "8px 4px" }}>班级</th>
                    <th style={{ padding: "8px 4px" }}>手机号</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredStudents.map((s) => (
                    <tr key={s.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "8px 4px" }}>{s.identifier}</td>
                      <td style={{ padding: "8px 4px" }}>{s.name ?? "—"}</td>
                      <td style={{ padding: "8px 4px" }}>{s.class_name ?? "—"}</td>
                      <td style={{ padding: "8px 4px" }}>{s.phone ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </div>
    </>
  );
}

export default function TeacherPage() {
  return (
    <AuthGate>
      <TeacherHome />
    </AuthGate>
  );
}
