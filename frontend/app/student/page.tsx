"use client";

import Link from "next/link";
import { useState } from "react";
import { AuthGate } from "@/components/auth-guard";
import { LogoutButton } from "@/components/logout-button";
import { SwitchChildButton } from "@/components/switch-child";
import { api, ApiError, type AnswerCitation } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

function StudentHome() {
  const currentStudent = useAuthStore((s) => s.currentStudent);
  const isPhoneLogin = useAuthStore((s) => s.isPhoneLogin);

  // 班级数据隔离：未分配班级时展示空状态，不发 API 请求
  const hasClass = currentStudent?.class_id != null;

  // AI 提问
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<AnswerCitation[]>([]);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setAnswer("");
    setCitations([]);
    try {
      const res = await api.askAI(question.trim());
      setAnswer(res.answer);
      setRemaining(res.remaining);
      setCitations(res.citations);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "提问失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <div className="topbar">
        <strong>CampusClaw 学生端</strong>
        <div className="actions">
          <Link href="/materials" className="btn" style={{ width: "auto", padding: "8px 16px", textDecoration: "none" }}>
            学习资料
          </Link>
          <SwitchChildButton />
          <LogoutButton />
        </div>
      </div>
      <div className="content">
        <h2 style={{ marginBottom: 12 }}>
          你好，{currentStudent?.name ?? "同学"}
        </h2>
        <p className="hint" style={{ marginBottom: 24 }}>
          {isPhoneLogin ? "当前为家长验证码登录" : "当前为学生本人登录"}
        </p>

        {!hasClass ? (
          <div className="card" style={{ textAlign: "center", padding: 32 }}>
            <p className="hint" style={{ fontSize: 16 }}>
              暂无班级
            </p>
            <p className="hint" style={{ marginTop: 8 }}>
              您尚未被分配到任何班级，请联系教师或管理员处理。
            </p>
          </div>
        ) : (
          <>
            <div className="card" style={{ marginBottom: 24 }}>
              <h3 style={{ marginBottom: 12 }}>AI 解题助手</h3>
              <p className="hint" style={{ marginBottom: 12 }}>
                每日最多 20 次提问{remaining !== null && `，今日剩余 ${remaining} 次`}
              </p>
              <form onSubmit={handleAsk} style={{ marginBottom: 12 }}>
                <input
                  className="input"
                  style={{ width: "70%", marginRight: 8 }}
                  placeholder="输入你的问题…"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  disabled={loading}
                />
                <button className="btn" style={{ width: "auto", padding: "8px 16px" }} type="submit" disabled={loading}>
                  {loading ? "提问中…" : "提问"}
                </button>
              </form>
              {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}
              {answer && (
                <div style={{ background: "#f9fafb", padding: 12, borderRadius: 8, fontSize: 14 }}>
                  <div style={{ whiteSpace: "pre-wrap" }}>{answer}</div>
                  {citations.length > 0 && (
                    <div style={{ marginTop: 12, borderTop: "1px solid #e5e7eb", paddingTop: 10 }}>
                      <strong style={{ fontSize: 13 }}>参考资料</strong>
                      <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13, lineHeight: 1.8 }}>
                        {citations.map((c, i) => (
                          <li key={`${c.material_id}-${c.chunk_index}`}>
                            <Link href="/materials" style={{ color: "#2563eb" }}>
                              {c.filename}（块 {c.chunk_index}）
                            </Link>
                            <span style={{ color: "#6b7280" }}>
                              {c.excerpt.replace(/^.{0,0}/, " ")}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>

            <ul style={{ lineHeight: 2, paddingLeft: 20 }}>
              <li>
                <Link href="/materials" style={{ color: "#2563eb" }}>查看本班资料</Link>
              </li>
              <li>提交作业</li>
              <li>查看个人错题本</li>
            </ul>
          </>
        )}
      </div>
    </>
  );
}

export default function StudentPage() {
  return (
    <AuthGate>
      <StudentHome />
    </AuthGate>
  );
}
