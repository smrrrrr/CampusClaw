"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, StudentBriefDTO, TokenDTO } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { StudentPicker, applyTokenSession } from "@/components/student-picker";

/**
 * "切换孩子"按钮：
 * - 仅多娃家长可见（store.canSwitchStudent）
 * - 点击调 switch-student 获取新 Temp Token 与学生列表
 * - 选择孩子后换发新 JWT，清空业务缓存并刷新页面数据
 */
export function SwitchChildButton() {
  const canSwitch = useAuthStore((s) => s.canSwitchStudent);
  const resetBusinessState = useAuthStore((s) => s.resetBusinessState);
  const setSession = useAuthStore((s) => s.setSession);
  const router = useRouter();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [picker, setPicker] = useState<{
    tempToken: string;
    students: StudentBriefDTO[];
  } | null>(null);

  if (!canSwitch) return null;

  const handleSwitch = async () => {
    setError("");
    setLoading(true);
    try {
      const data = await api.switchStudent();
      if (data.temp_token && data.students && data.students.length > 1) {
        setPicker({ tempToken: data.temp_token, students: data.students });
      } else if (data.message) {
        setError(data.message);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        useAuthStore.getState().reset();
        router.replace("/login");
        return;
      }
      setError(err instanceof ApiError ? err.message : "切换失败");
    } finally {
      setLoading(false);
    }
  };

  const handleSelected = (data: TokenDTO) => {
    // 切换成功：先清空业务缓存（作业、AI 历史、错题本），再写入新会话。
    // Access Token 仅存于内存（Zustand），严禁硬刷新页面（会丢失会话）；
    // 业务页面依赖 currentStudent.id 的 effect 自动重新拉取数据。
    resetBusinessState();
    applyTokenSession(data, setSession, true, true);
    setPicker(null);
    router.replace("/student");
  };

  return (
    <>
      <button className="btn btn-secondary" style={{ width: "auto", padding: "8px 16px" }} onClick={handleSwitch} disabled={loading}>
        {loading ? "加载中…" : "切换孩子"}
      </button>
      {error && <span className="error" style={{ marginBottom: 0 }}>{error}</span>}
      {picker && (
        <StudentPicker
          tempToken={picker.tempToken}
          students={picker.students}
          onCancel={() => setPicker(null)}
          onSelected={handleSelected}
        />
      )}
    </>
  );
}
