"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import { AuthGate } from "@/components/auth-guard";
import { AppShell } from "@/components/app-layout";
import { LogoutButton } from "@/components/logout-button";
import { SwitchChildButton } from "@/components/switch-child";
import MarkdownAnswer from "@/components/markdown-answer";
import { ToolCalls } from "@/components/tool-calls";
import {
  api,
  learningApi,
  streamChat,
  type AnswerCitation,
  type ConversationItemDTO,
  type ConversationMessageDTO,
  type ToolCallDTO,
  type StudentApplicationDTO,
} from "@/lib/api";
import { useAuthStore } from "@/lib/store";

function StudentHome() {
  const currentStudent = useAuthStore((s) => s.currentStudent);
  const isPhoneLogin = useAuthStore((s) => s.isPhoneLogin);
  const router = useRouter();

  // 班级数据隔离：未分配班级时展示空状态，不发 API 请求
  const hasClass = currentStudent?.class_id != null;

  // 打开/下载命中的原始文件（标注出处，可回溯原文）
  const openOriginal = (c: AnswerCitation) => {
    const token = useAuthStore.getState().accessToken;
    fetch(api.materialDownloadUrl(c.material_id), {
      headers: { Authorization: `Bearer ${token}` },
      credentials: "include",
    })
      .then((res) => res.blob())
      .then((blob) => {
        const objUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = objUrl;
        a.download = c.filename;
        a.click();
        URL.revokeObjectURL(objUrl);
      });
  };

  // 多轮会话状态
  const [conversations, setConversations] = useState<ConversationItemDTO[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ConversationMessageDTO[]>([]);
  const [question, setQuestion] = useState("");
  const [remaining, setRemaining] = useState<number | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [toolCalls, setToolCalls] = useState<ToolCallDTO[]>([]);
  const [streamCites, setStreamCites] = useState<AnswerCitation[]>([]);
  const [error, setError] = useState("");
  const [applications, setApplications] = useState<StudentApplicationDTO[]>([]);
  const [applicationId, setApplicationId] = useState<number | null>(null);
  const awaitingLocation = messages[messages.length - 1]?.tool_calls?.some(call => call.status === "needs_input") ?? false;

  const loadConversations = useCallback(async () => {
    try {
      const list = await api.listConversations();
      setConversations(list);
    } catch {
      /* 列表加载失败不阻塞 */
    }
  }, []);

  // 进入页面 / 切换子女（class_id 变化）时重载会话列表
  useEffect(() => {
    if (!hasClass) return;
    setActiveId(null);
    setMessages([]);
    setStreaming(false);
    setLoadingConversation(false);
    setError("");
    setApplications([]); setApplicationId(null);
    let alive = true;
    learningApi.studentApplications().then(rows => { if (alive) setApplications(rows); })
      .catch(e => { if (alive) setError(e.message); });
    loadConversations();
    return () => { alive = false; };
  }, [hasClass, currentStudent?.id, loadConversations]);

  const selectConversation = async (id: number) => {
    if (streaming || loadingConversation) return;
    setLoadingConversation(true);
    setActiveId(id);
    setApplicationId(conversations.find(c => c.id === id)?.application_id ?? null);
    setMessages([]);
    setError("");
    try {
      const msgs = await api.getConversationMessages(id);
      setMessages(msgs);
    } catch (e) { setError(e instanceof Error ? e.message : "读取会话失败"); }
    finally { setLoadingConversation(false); }
  };

  const newConversation = async () => {
    if (streaming || loadingConversation) return;
    setLoadingConversation(true);
    try {
      const c = await api.createConversation(undefined, applicationId);
      setConversations((prev) => [c, ...prev]);
      setActiveId(c.id);
      setMessages([]);
      setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "新建对话失败"); }
    finally { setLoadingConversation(false); }
  };

  const removeConversation = async (id: number) => {
    if (streaming || loadingConversation) return;
    try {
      await api.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setMessages([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || streaming || loadingConversation) return;
    setError("");
    setStreaming(true);

    let cid = activeId;
    if (cid == null) {
      let c: ConversationItemDTO;
      try { c = await api.createConversation(undefined, applicationId); }
      catch (e) { setError(e instanceof Error ? e.message : "新建对话失败"); setStreaming(false); return; }
      setConversations((prev) => [c, ...prev]);
      cid = c.id;
      setActiveId(c.id);
    }

    // 乐观展示用户消息
    setMessages((prev) => [
      ...prev,
      { id: -Date.now(), role: "user", content: q, sources: [], created_at: "" },
    ]);
    setQuestion("");
    setStreaming(true);
    setStreamText("");
    setToolCalls([]);
    setStreamCites([]);

    // 局部累加，避免回调内读取过期的 state
    let acc = "";
    await streamChat(cid, q, {
      onMeta: setToolCalls,
      onDelta: (t) => {
        acc += t;
        setStreamText(acc);
      },
      onDone: (d) => {
        setMessages((prev) => [
          ...prev,
          {
            id: -Date.now() - 1,
            role: "assistant",
            content: d.answer,
            sources: d.citations,
            tool_calls: d.tool_calls,
            created_at: "",
          },
        ]);
        setRemaining(d.remaining);
        setStreamText("");
        setStreamCites([]);
        setStreaming(false);
        loadConversations();
      },
      onError: (m) => {
        // 已吐出部分内容时保留为答案
        if (acc) {
          setMessages((prev) => [
            ...prev,
            {
              id: -Date.now() - 2,
              role: "assistant",
              content: acc,
              sources: streamCites,
              created_at: "",
            },
          ]);
        }
        setError(m);
        setStreamText("");
        setStreamCites([]);
        setStreaming(false);
      },
    });
  };

  return (
    <AppShell
      brandMark="S"
      subtitle="学习平台 · 学生端"
      navItems={[
        { key: "home", label: "首页", icon: "chat" },
        { key: "materials", label: "学习资料", icon: "doc" },
      ]}
      active="home"
      onNavigate={(key) => {
        if (key === "materials") router.push("/materials");
      }}
      headerRight={
        <>
          <button className="hdr-btn" onClick={() => router.push("/materials")}>学习资料</button>
          <SwitchChildButton />
          <LogoutButton />
        </>
      }
    >
      <div className="content" style={{ padding: 0, maxWidth: "none" }}>
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
          <div className="card">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 12,
              }}
            >
              <h3 style={{ margin: 0 }}>{applications.find(a => a.id === applicationId)?.name ?? "通用解题助手"}</h3>
              <button
                className="btn"
                onClick={newConversation}
                disabled={streaming || loadingConversation}
                style={{ width: "auto", padding: "6px 14px" }}
              >
                新对话
              </button>
            </div>
            <div className="field"><label htmlFor="student-application">选择学习助手</label>
              <select id="student-application" value={applicationId ?? ""} disabled={streaming || loadingConversation} onChange={e => {
                setApplicationId(e.target.value ? Number(e.target.value) : null); setActiveId(null); setMessages([]); setToolCalls([]); setError("");
              }}><option value="">通用解题助手</option>{applications.map(app => <option key={app.id} value={app.id}>{app.name}{app.tutor_enabled ? " · 解题引导" : ""}</option>)}</select>
              <p className="hint">切换助手会开始独立对话；历史会话保留原来的学科。{activeId !== null && `当前会话 ID：${activeId}`}</p>
            </div>
            <p className="hint" style={{ marginBottom: 12 }}>
              支持连续追问，同一会话内记住前文
              {remaining !== null && `，今日剩余 ${remaining} 次`}
            </p>

            <div style={{ display: "flex", gap: 16, minHeight: 420 }}>
              {/* 左侧会话列表 */}
              <aside
                style={{
                  width: 220,
                  flexShrink: 0,
                  border: "1px solid #f3f4f6",
                  borderRadius: 8,
                  overflow: "auto",
                  maxHeight: 480,
                }}
              >
                {conversations.length === 0 ? (
                  <p className="hint" style={{ padding: 12 }}>
                    暂无会话，点击「新对话」开始
                  </p>
                ) : (
                  conversations.map((c) => (
                    <div
                      key={c.id}
                      onClick={() => selectConversation(c.id)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                        padding: "8px 10px",
                        cursor: "pointer",
                        fontSize: 13,
                        borderBottom: "1px solid #f3f4f6",
                        background: c.id === activeId ? "#fbeef2" : "transparent",
                        color: c.id === activeId ? "#8b1538" : "#374151",
                      }}
                    >
                      <span
                        style={{
                          flex: 1,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={c.title}
                      >
                        {c.application_id ? `[${applications.find(a => a.id === c.application_id)?.name ?? "学科"}] ` : ""}{c.title}
                      </span>
                      <button
                        title="删除会话"
                        onClick={(e) => {
                          e.stopPropagation();
                          removeConversation(c.id);
                        }}
                        style={{
                          border: "none",
                          background: "transparent",
                          color: "#9ca3af",
                          cursor: "pointer",
                          fontSize: 14,
                          lineHeight: 1,
                          padding: "2px 4px",
                        }}
                      >
                        ×
                      </button>
                    </div>
                  ))
                )}
              </aside>

              {/* 右侧消息线程 */}
              <section style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
                {error && <div className="error" style={{ margin: 0 }}>{error}</div>}
                <div
                  style={{
                    flex: 1,
                    border: "1px solid #f3f4f6",
                    borderRadius: 8,
                    padding: 12,
                    overflow: "auto",
                    maxHeight: 380,
                    background: "#fafafa",
                  }}
                >
                  {messages.length === 0 && !streaming ? (
                    <p className="hint" style={{ padding: 8 }}>
                      输入问题开始对话，或选择一个历史会话继续追问。
                    </p>
                  ) : (
                    messages.map((m) => (
                      <div key={m.id} style={{ marginBottom: 12 }}>
                        <div
                          style={{
                            display: "flex",
                            alignItems: "flex-start",
                            gap: 8,
                          }}
                        >
                          <span
                            style={{
                              flexShrink: 0,
                              fontSize: 12,
                              fontWeight: 700,
                              marginTop: 4,
                              color: m.role === "user" ? "#2563eb" : "#8b1538",
                            }}
                          >
                            {m.role === "user" ? "我" : "AI"}
                          </span>
                          <div style={{ flex: 1 }}>
                            {m.role === "user" ? (
                              <div
                                style={{
                                  background: "#fff",
                                  padding: 8,
                                  borderRadius: 8,
                                  fontSize: 14,
                                  whiteSpace: "pre-wrap",
                                }}
                              >
                                {m.content}
                              </div>
                            ) : (
                              <>
                                <ToolCalls calls={m.tool_calls ?? []} />
                                <div style={{ background: "#fff", padding: 8, borderRadius: 8, fontSize: 14 }}>
                                  <MarkdownAnswer text={m.content} />
                                </div>
                                {m.sources.length > 0 && (
                                  <div
                                    style={{
                                      marginTop: 8,
                                      background: "#fff",
                                      border: "1px solid #e5e7eb",
                                      padding: 10,
                                      borderRadius: 8,
                                    }}
                                  >
                                    <strong style={{ fontSize: 12 }}>参考资料（标注出处）</strong>
                                    <ul style={{ margin: "8px 0 0", paddingLeft: 16, fontSize: 12, lineHeight: 1.5 }}>
                                      {m.sources.map((c) => (
                                        <li key={`${c.material_id}-${c.chunk_index}`} style={{ marginBottom: 6 }}>
                                          <span style={{ color: "#8b1538", fontWeight: 600 }}>{c.filename}</span>
                                          <span className="hint"> · 第 {c.chunk_index} 块</span>
                                          <button
                                            className="btn"
                                            style={{ width: "auto", padding: "1px 8px", fontSize: 11, marginLeft: 6 }}
                                            onClick={() => openOriginal(c)}
                                          >
                                            查看原文
                                          </button>
                                          <div className="citation-excerpt">
                                            <MarkdownAnswer text={c.excerpt} />
                                          </div>
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                  {streaming && (
                    <div style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                      <span style={{ flexShrink: 0, fontSize: 12, fontWeight: 700, marginTop: 4, color: "#8b1538" }}>
                        AI
                      </span>
                      <div style={{ flex: 1, background: "#fff", padding: 8, borderRadius: 8, fontSize: 14 }}>
                        <ToolCalls calls={toolCalls} />
                        {!streamText && <p className="hint">正在处理问题与工具请求…</p>}
                        <MarkdownAnswer text={streamText + "▍"} />
                      </div>
                    </div>
                  )}
                </div>

                <form onSubmit={handleSend} style={{ display: "flex", gap: 8 }}>
                  <input
                    className="input"
                    style={{ flex: 1 }}
                    placeholder={awaitingLocation ? "请输入城市或区县，例如：北京市大兴区" : "输入你的问题，回车发送…"}
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    disabled={streaming || loadingConversation}
                  />
                  <button
                    className="btn"
                    style={{ width: "auto", padding: "8px 18px" }}
                    type="submit"
                    disabled={streaming || loadingConversation || !question.trim()}
                  >
                    {streaming ? "生成中…" : "发送"}
                  </button>
                </form>
              </section>
            </div>

            <ul style={{ lineHeight: 2, paddingLeft: 20, marginTop: 16 }}>
              <li>
                <Link href="/materials" style={{ color: "#8b1538" }}>查看本班资料</Link>
              </li>
              <li>提交作业</li>
              <li>查看个人错题本</li>
            </ul>
          </div>
        )}
      </div>
    </AppShell>
  );
}

export default function StudentPage() {
  return (
    <AuthGate>
      <StudentHome />
    </AuthGate>
  );
}
