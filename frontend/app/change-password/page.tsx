"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, TokenDTO } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { applyTokenSession } from "@/components/student-picker";

export default function ChangePasswordPage() {
  const router = useRouter();
  const setSession = useAuthStore((s) => s.setSession);
  const accessToken = useAuthStore((s) => s.accessToken);
  const mustChangePassword = useAuthStore((s) => s.mustChangePassword);
  const isPhoneLogin = useAuthStore((s) => s.isPhoneLogin);

  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // 未登录去登录页；验证码登录或无需改密则离开本页
  useEffect(() => {
    if (!accessToken) {
      router.replace("/login");
    } else if (isPhoneLogin || !mustChangePassword) {
      const role = useAuthStore.getState().userRole;
      router.replace(role === "teacher" ? "/teacher" : "/student");
    }
  }, [accessToken, isPhoneLogin, mustChangePassword, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (newPassword !== confirmPassword) {
      setError("两次输入的新密码不一致");
      return;
    }

    setLoading(true);
    try {
      const data: TokenDTO = await api.changePassword(oldPassword, newPassword);
      applyTokenSession(data, setSession, false, useAuthStore.getState().canSwitchStudent);
      router.replace(data.role === "teacher" ? "/teacher" : "/student");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "修改失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="centered">
      <div className="card">
        <h1>修改初始密码</h1>
        {error && <div className="error">{error}</div>}
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label>旧密码</label>
            <input
              type="password"
              value={oldPassword}
              onChange={(e) => setOldPassword(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label>新密码</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
            <div className="hint">
              至少 8 位，须同时包含大写字母、小写字母、数字和特殊字符
            </div>
          </div>
          <div className="field">
            <label>确认新密码</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
          </div>
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "提交中…" : "确认修改"}
          </button>
        </form>
      </div>
    </div>
  );
}
