"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AuthGate } from "@/components/auth-guard";
import { AppShell } from "@/components/app-layout";
import { ClassSelector } from "@/components/class-selector";
import { LogoutButton } from "@/components/logout-button";
import { api, ApiError, type AgentConfigDTO } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

interface StudentRow {
  id: number;
  identifier: string;
  name: string | null;
  class_id: number | null;
  class_name: string | null;
  phone: string | null;
}

type View = "home" | "agent" | "materials" | "tools" | "audit" | "mcp" | "applications" | "invocations";

function TeacherHome() {
  const router = useRouter();
  const teachingClasses = useAuthStore((s) => s.teachingClasses);
  const [view, setView] = useState<View>("home");
  const [classId, setClassId] = useState<number | null>(null);
  const [students, setStudents] = useState<StudentRow[]>([]);
  const [loadingStudents, setLoadingStudents] = useState(false);
  const [error, setError] = useState("");

  const hasClasses = teachingClasses != null && teachingClasses.length > 0;

  // 重置密码
  const [resetMsg, setResetMsg] = useState("");
  const [resettingId, setResettingId] = useState<number | null>(null);

  // AI 助手配置
  const [cfgPrompt, setCfgPrompt] = useState("");
  const [cfgTutor, setCfgTutor] = useState(true);
  const [cfgLoading, setCfgLoading] = useState(false);
  const [cfgSaving, setCfgSaving] = useState(false);
  const [cfgMsg, setCfgMsg] = useState("");
  const [cfgError, setCfgError] = useState("");
  const defaultPromptRef = useRef("");

  useEffect(() => {
    api
      .getAgentDefaultPrompt()
      .then((d) => (defaultPromptRef.current = d.system_prompt))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (classId === null) return;
    setCfgLoading(true);
    setCfgMsg("");
    setCfgError("");
    api
      .getAgentConfig(classId)
      .then((cfg: AgentConfigDTO) => {
        setCfgPrompt(cfg.system_prompt);
        setCfgTutor(cfg.tutor_enabled);
      })
      .catch((e) => setCfgError(e instanceof ApiError ? e.message : "加载配置失败"))
      .finally(() => setCfgLoading(false));
  }, [classId]);

  const saveAgentConfig = async () => {
    if (classId === null) return;
    setCfgSaving(true);
    setCfgMsg("");
    setCfgError("");
    try {
      await api.saveAgentConfig({
        class_id: classId,
        system_prompt: cfgPrompt,
        tutor_enabled: cfgTutor,
      });
      setCfgMsg("已保存。学生端下次提问将使用此提示词与技能设置。");
    } catch (e) {
      setCfgError(e instanceof ApiError ? e.message : "保存失败");
    } finally {
      setCfgSaving(false);
    }
  };

  // 默认选第一个任教班级
  useEffect(() => {
    if (classId === null && hasClasses) setClassId(teachingClasses![0]);
  }, [teachingClasses, classId, hasClasses]);

  // 拉取学生列表（API 不携带 class_id，后端从 JWT teaching_classes 过滤）
  useEffect(() => {
    if (classId === null) return;
    setLoadingStudents(true);
    setError("");
    setResetMsg("");
    api
      .listStudents()
      .then((data) =>
        setStudents(
          data.items.map((s) => ({
            id: s.id,
            identifier: s.identifier,
            name: s.name,
            class_id: s.class_id,
            class_name: s.class_name,
            phone: s.phone,
          })),
        ),
      )
      .catch((e) => setError(e instanceof ApiError ? e.message : "加载学生列表失败"))
      .finally(() => setLoadingStudents(false));
  }, [classId]);

  const handleResetPassword = async (s: StudentRow) => {
    if (!window.confirm(`确定重置「${s.name ?? s.identifier}」的密码为初始密码吗？`)) return;
    setResettingId(s.id);
    setError("");
    setResetMsg("");
    try {
      const res = await api.resetStudentPassword(s.id);
      setResetMsg(`${res.message}，初始密码：${res.initial_password}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "重置失败");
    } finally {
      setResettingId(null);
    }
  };

  const filteredStudents =
    classId !== null ? students.filter((s) => s.class_id === classId) : students;
  const className = filteredStudents[0]?.class_name ?? (classId ? `班级 ${classId}` : "");

  const navItems: { key: View; label: string; icon: string; to?: string }[] = [
    { key: "home", label: "本班首页", icon: "home" },
    { key: "materials", label: "讲义管理", icon: "doc", to: "/materials" },
    { key: "agent", label: "助手配置", icon: "robot" },
    { key: "applications", label: "学科应用与模板", icon: "robot", to: "/teacher/applications" },
    { key: "mcp", label: "工具与技能", icon: "tools", to: "/teacher/mcp" },
    { key: "invocations", label: "调用验证", icon: "log", to: "/teacher/invocations" },
    { key: "tools", label: "作业与改分", icon: "tools" },
    { key: "audit", label: "审计与统计", icon: "audit" },
  ];

  const handleNav = (key: string) => {
    const item = navItems.find((n) => n.key === key);
    if (!item) return;
    if (item.to) {
      router.push(item.to);
      return;
    }
    setView(item.key);
  };

  return (
    <AppShell
      brandMark="T"
      subtitle="智能教学平台 · 教师端"
      navItems={navItems}
      active={view}
      onNavigate={handleNav}
      headerLeft={
        <>
          <span className="status-dot" />
          {hasClasses && <span className="class-pill">{className || `班级 ${classId}`}</span>}
          {hasClasses && <ClassSelector value={classId} onChange={setClassId} />}
        </>
      }
      headerRight={
        <>
          <button className="hdr-btn" onClick={() => router.push("/login")}>切换账号</button>
          <span className="user-chip">
            <span className="avatar">师</span>
            教师
          </span>
          <LogoutButton />
        </>
      }
    >
      <div style={{ padding: 0 }}>
          {!hasClasses ? (
            <div className="panel" style={{ textAlign: "center", padding: "56px 32px" }}>
              <p className="hint" style={{ fontSize: 16 }}>
                暂无任教班级
              </p>
              <p className="hint" style={{ marginTop: 8 }}>
                您尚未被分配任教班级，请联系管理员处理。
              </p>
            </div>
          ) : view === "home" ? (
            <>
              <div className="page-title" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
                <div>
                  <h2>本班学生</h2>
                  <p>查看本班学生、重置初始密码。学生首次登录需使用初始密码并修改密码。</p>
                </div>
                <Link href="/teacher/upload" className="btn-pill">
                  上传资料
                </Link>
              </div>

              {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}
              {resetMsg && <div className="success" style={{ marginBottom: 8 }}>{resetMsg}</div>}

              {loadingStudents ? (
                <div className="panel"><p className="hint">加载中…</p></div>
              ) : filteredStudents.length === 0 ? (
                <div className="panel" style={{ textAlign: "center", padding: "44px 24px" }}>
                  <p className="hint">暂无学生</p>
                </div>
              ) : (
                <div className="table-card">
                  <table>
                    <thead>
                      <tr>
                        <th>学号</th>
                        <th>姓名</th>
                        <th>班级</th>
                        <th>手机号</th>
                        <th style={{ width: 140 }}>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredStudents.map((s) => (
                        <tr key={s.id}>
                          <td style={{ fontVariantNumeric: "tabular-nums" }}>{s.identifier}</td>
                          <td>{s.name ?? "—"}</td>
                          <td>{s.class_name ?? "—"}</td>
                          <td>{s.phone ?? "—"}</td>
                          <td>
                            <button
                              className="btn-pill ghost sm"
                              onClick={() => handleResetPassword(s)}
                              disabled={resettingId !== null}
                            >
                              {resettingId === s.id ? "重置中…" : "重置密码"}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : view === "agent" ? (
            <>
              <div className="page-title" style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
                <div>
                  <h2>AI 助手配置</h2>
                  <p>按班级自定义学生的 AI 解题助手提示词与解题引导技能。</p>
                </div>
                <span className={"chip " + (cfgTutor ? "green" : "red")}>
                  {cfgTutor ? "解题引导已启用" : "解题引导未启用"}
                </span>
              </div>

              <div className="panel" style={{ maxWidth: 720 }}>
                {cfgError && <div className="error">{cfgError}</div>}
                {cfgMsg && <div className="success">{cfgMsg}</div>}
                {cfgLoading ? (
                  <p className="hint">加载中…</p>
                ) : (
                  <>
                    <div className="field">
                      <label>角色提示词（可自定义，留空则使用默认）</label>
                      <textarea
                        value={cfgPrompt}
                        onChange={(e) => {
                          setCfgPrompt(e.target.value);
                          setCfgMsg("");
                        }}
                        rows={8}
                        placeholder="留空使用默认提示词"
                      />
                      <p className="hint" style={{ marginTop: 6 }}>
                        开启解题引导时，此自定义提示词会被屏蔽。此处配置通用助手；各学科请进入「学科应用与模板」。
                        提示词中应保留 LaTeX 公式定界符（$...$ 行内 / $$...$$ 独立）与[编号]标注规范，避免前端渲染源码。
                      </p>
                    </div>

                    <div className="row-inline" style={{ marginBottom: 14 }}>
                      <button
                        className="btn-pill ghost sm"
                        onClick={() => {
                          setCfgPrompt(defaultPromptRef.current);
                          setCfgMsg("");
                        }}
                      >
                        填入默认提示词
                      </button>
                      <button
                        className="btn-pill ghost sm"
                        onClick={() => {
                          setCfgPrompt("");
                          setCfgMsg("");
                        }}
                      >
                        清空（恢复默认）
                      </button>
                    </div>

                    <div className="kv-row">
                      <input
                        type="checkbox"
                        id="tutor-skill"
                        checked={cfgTutor}
                        onChange={(e) => {
                          setCfgTutor(e.target.checked);
                          setCfgMsg("");
                        }}
                      />
                      <label htmlFor="tutor-skill">
                        开启「解题引导」技能（只给思路、不直接给最终答案）
                      </label>
                    </div>

                    <button className="btn-pill" onClick={saveAgentConfig} disabled={cfgSaving}>
                      {cfgSaving ? "保存中…" : "保存配置"}
                    </button>
                  </>
                )}
              </div>
            </>
          ) : (
            <div className="panel" style={{ textAlign: "center", padding: "56px 32px" }}>
              <p className="hint" style={{ fontSize: 16 }}>
                {navItems.find((n) => n.key === view)?.label ?? view}
              </p>
              <p className="hint" style={{ marginTop: 8 }}>
                该模块尚未接入，敬请期待。
              </p>
            </div>
          )}
      </div>
    </AppShell>
  );
}

export default function TeacherPage() {
  return (
    <AuthGate>
      <TeacherHome />
    </AuthGate>
  );
}
