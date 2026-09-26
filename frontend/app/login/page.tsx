"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, StudentBriefDTO, TokenDTO } from "@/lib/api";
import { useAuthStore } from "@/lib/store";
import { StudentPicker, applyTokenSession } from "@/components/student-picker";

type Tab = "password" | "code";

export default function LoginPage() {
  const router = useRouter();
  const setSession = useAuthStore((s) => s.setSession);
  const accessToken = useAuthStore((s) => s.accessToken);

  const [tab, setTab] = useState<Tab>("password");
  const [error, setError] = useState("");
  const [forgotHint, setForgotHint] = useState(false);
  const [loading, setLoading] = useState(false);

  // 密码登录表单
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");

  // 验证码登录表单
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [countdown, setCountdown] = useState(0);

  // 多娃选择
  const [picker, setPicker] = useState<{
    tempToken: string;
    students: StudentBriefDTO[];
  } | null>(null);

  useEffect(() => {
    if (countdown <= 0) return;
    const timer = setTimeout(() => setCountdown((v) => v - 1), 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  // 已登录用户访问登录页 → 按角色跳走
  useEffect(() => {
    if (accessToken) {
      const role = useAuthStore.getState().userRole;
      router.replace(role === "teacher" ? "/teacher" : "/student");
    }
  }, [accessToken, router]);

  const gotoRoleHome = (role: "teacher" | "student", mustChange: boolean, isPhone: boolean) => {
    if (!isPhone && mustChange) {
      router.replace("/change-password");
    } else {
      router.replace(role === "teacher" ? "/teacher" : "/student");
    }
  };

  const handlePasswordLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setForgotHint(false);
    setLoading(true);
    try {
      const data: TokenDTO = await api.login(identifier.trim(), password);
      applyTokenSession(data, setSession, false, false);
      gotoRoleHome(data.role, data.must_change_password, false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  const handleSendCode = async () => {
    setError("");
    if (!/^1\d{10}$/.test(phone)) {
      setError("请输入正确的 11 位手机号");
      return;
    }
    try {
      await api.sendCode(phone);
      setCountdown(60);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "验证码发送失败");
    }
  };

  const handleVerifyCode = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await api.verifyCode(phone, code);
      if (data.temp_token && data.students && data.students.length > 1) {
        // 多娃：弹出选择框
        setPicker({ tempToken: data.temp_token, students: data.students });
        return;
      }
      if (data.access_token && data.user) {
        // 单娃：直接进入
        const tokenData: TokenDTO = {
          access_token: data.access_token,
          token_type: data.token_type ?? "bearer",
          must_change_password: data.must_change_password ?? false,
          role: data.role!,
          user: data.user,
        };
        applyTokenSession(tokenData, setSession, true, false);
        router.replace("/student");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "验证码校验失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="centered">
      <div className="card">
        <h1 style={{ color: "#7e202b" }}>CampusClaw 校园助手</h1>

        <div className="tabs">
          <button
            className={tab === "password" ? "active" : ""}
            onClick={() => {
              setTab("password");
              setError("");
              setForgotHint(false);
            }}
          >
            密码登录
          </button>
          <button
            className={tab === "code" ? "active" : ""}
            onClick={() => {
              setTab("code");
              setError("");
              setForgotHint(false);
            }}
          >
            验证码登录
          </button>
        </div>

        {error && <div className="error">{error}</div>}

        {tab === "password" ? (
          <form onSubmit={handlePasswordLogin}>
            <div className="field">
              <label>学号 / 工号</label>
              <input
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                placeholder="请输入学号或工号"
                required
              />
            </div>
            <div className="field">
              <label>密码</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码"
                required
              />
            </div>
            <button className="btn" type="submit" disabled={loading}>
              {loading ? "登录中…" : "登 录"}
            </button>
            <div style={{ marginTop: 12, textAlign: "center" }}>
              <button
                type="button"
                className="link-like"
                onClick={() => setForgotHint((v) => !v)}
              >
                忘记密码？
              </button>
              {forgotHint && (
                <div className="hint" style={{ marginTop: 6 }}>
                  请联系班主任重置
                </div>
              )}
            </div>
          </form>
        ) : (
          <form onSubmit={handleVerifyCode}>
            <div className="field">
              <label>手机号</label>
              <input
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="请输入绑定的手机号"
                maxLength={11}
                required
              />
            </div>
            <div className="field">
              <label>验证码</label>
              <div className="row-inline">
                <input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="6 位验证码"
                  maxLength={6}
                  required
                />
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ width: 130 }}
                  onClick={handleSendCode}
                  disabled={countdown > 0}
                >
                  {countdown > 0 ? `${countdown}s 后重发` : "发送验证码"}
                </button>
              </div>
            </div>
            <button className="btn" type="submit" disabled={loading}>
              {loading ? "校验中…" : "登 录"}
            </button>
          </form>
        )}
      </div>

      {picker && (
        <StudentPicker
          tempToken={picker.tempToken}
          students={picker.students}
          onCancel={() => setPicker(null)}
        />
      )}
    </div>
  );
}
