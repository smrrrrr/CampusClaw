"use client";

import { useState } from "react";
import { api, ApiError, StudentBriefDTO, TokenDTO, setRoleCookies } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { useRouter } from "next/navigation";

/**
 * 多娃选择弹窗：
 * - students.length > 1 时展示
 * - 选择后调用 select-student 换取正式 JWT，写入全局会话
 */
export function StudentPicker({
  tempToken,
  students,
  onCancel,
  onSelected,
}: {
  tempToken: string;
  students: StudentBriefDTO[];
  onCancel?: () => void;
  // 切换孩子流程可自定义选择成功后的处理（清缓存 + 刷新）
  onSelected?: (data: TokenDTO) => void;
}) {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState<number | null>(null);
  const setSession = useAuthStore((s) => s.setSession);
  const router = useRouter();

  const handleSelect = async (studentId: number) => {
    setError("");
    setLoading(studentId);
    try {
      const data: TokenDTO = await api.selectStudent(tempToken, studentId);
      if (onSelected) {
        onSelected(data);
        return;
      }
      applyTokenSession(data, setSession, true, students.length > 1);
      router.replace(data.role === "teacher" ? "/teacher" : "/student");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "选择失败，请重试");
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="modal-mask">
      <div className="modal">
        <h2 style={{ marginBottom: 16, fontSize: 18 }}>请选择当前要查看的孩子</h2>
        {error && <div className="error">{error}</div>}
        {students.map((s) => (
          <button
            key={s.id}
            className="student-option"
            disabled={loading !== null}
            onClick={() => handleSelect(s.id)}
          >
            <div style={{ fontWeight: 600 }}>{s.name ?? `学生 ${s.id}`}</div>
            <div className="hint">{s.class_name ?? "未分配班级"}</div>
          </button>
        ))}
        {onCancel && (
          <button className="link-like" style={{ marginTop: 8 }} onClick={onCancel}>
            返回重新登录
          </button>
        )}
      </div>
    </div>
  );
}

/** 将 TokenDTO 应用到全局会话（登录 / 多娃选择共用）。 */
export function applyTokenSession(
  data: TokenDTO,
  setSession: ReturnType<typeof useAuthStore.getState>["setSession"],
  isPhoneLogin: boolean,
  canSwitchStudent: boolean,
) {
  setSession({
    accessToken: data.access_token,
    userRole: data.role,
    mustChangePassword: data.must_change_password,
    isPhoneLogin,
    currentStudent: {
      id: data.user.id,
      name: data.user.name,
      class_id: data.user.class_id,
    },
    canSwitchStudent,
    teachingClasses: data.user.teaching_classes ?? null,
  });
  setRoleCookies(data.role);
}
