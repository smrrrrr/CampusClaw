"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthGate } from "@/components/auth-guard";
import { AppShell, TEACHER_NAV } from "@/components/app-layout";
import { ClassSelector } from "@/components/class-selector";
import { LogoutButton } from "@/components/logout-button";
import { learningApi, type InvocationDTO } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

const phases: Record<string, string> = { llm_answer: "模型生成回答", llm_tool_arguments: "模型提取工具参数", mcp_rpc: "MCP 协议调用", llm_skipped: "跳过模型调用" };
function InvocationsHome() {
  const router = useRouter();
  const classes = useAuthStore(s => s.teachingClasses);
  const [classId, setClassId] = useState<number | null>(classes?.[0] ?? null);
  const [conversation, setConversation] = useState("");
  const [trace, setTrace] = useState("");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<InvocationDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [detail, setDetail] = useState<InvocationDTO | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const scope = `${classId}/${conversation}/${trace}/${offset}`;
  const activeScope = useRef(scope); activeScope.current = scope;
  const params = useCallback((page = true) => {
    const q = new URLSearchParams({ class_id: String(classId) });
    if (conversation) q.set("conversation_id", conversation);
    if (trace) q.set("trace_id", trace);
    if (page) { q.set("offset", String(offset)); q.set("limit", "30"); }
    return q;
  }, [classId, conversation, trace, offset]);
  const reload = useCallback(async () => {
    if (classId === null) return;
    const target = scope;
    setBusy(true); setError("");
    try { const data = await learningApi.audits(params()); if (activeScope.current === target) { setItems(data.items); setTotal(data.total); } }
    catch (e) { if (activeScope.current === target) setError(e instanceof Error ? e.message : "加载失败"); }
    finally { if (activeScope.current === target) setBusy(false); }
  }, [classId, params, scope]);
  useEffect(() => { setItems([]); setTotal(0); setDetail(null); void reload(); }, [reload]);

  const exportRecords = async () => {
    setBusy(true); setError("");
    try {
      const data = await learningApi.exportAudits(params(false));
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" }));
      const a = document.createElement("a"); a.href = url; a.download = `llm-audits-${classId}.json`; a.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(e instanceof Error ? e.message : "导出失败"); }
    finally { setBusy(false); }
  };

  return <AppShell subtitle="智能教学平台 · 教师端" navItems={TEACHER_NAV} active="invocations"
    onNavigate={key => router.push(TEACHER_NAV.find(n => n.key === key)?.to ?? "/teacher")}
    headerLeft={<ClassSelector value={classId} onChange={id => { setClassId(id); setOffset(0); setConversation(""); setTrace(""); }} />} headerRight={<LogoutButton />} navFoot="真实调用正文 · 脱敏导出">
    <div className="page-title"><h2>调用验证</h2><p>查看每次提问实际发送的参数、模型返回、检索引用与技能命中信息。同一追踪编号属于同一次提问。</p></div>
    <p className="hint">记录从本功能启用后开始保存。认证头不保存，已配置密钥、手机号和邮箱会脱敏；跳过模型的记录会注明原因。</p>
    {error && <div className="error" role="alert">{error}</div>}
    {classId === null ? <p>暂无任教班级。</p> : <>
      <div className="panel"><div className="audit-filters">
        <div className="field"><label htmlFor="audit-conversation">会话 ID</label><input id="audit-conversation" type="number" min="1" value={conversation} onChange={e => { setConversation(e.target.value); setOffset(0); }} /></div>
        <div className="field"><label htmlFor="audit-trace">追踪编号</label><input id="audit-trace" value={trace} onChange={e => { setTrace(e.target.value); setOffset(0); }} /></div>
        <button className="btn-pill ghost" disabled={busy} onClick={() => void reload()}>刷新</button>
        <button className="btn-pill" disabled={busy || !total} onClick={() => void exportRecords()}>导出脱敏 JSON</button>
      </div>
      <p className="hint">共 {total} 条{busy ? " · 加载中…" : ""}</p>
      <div className="data-table-wrap"><table className="data-table"><thead><tr><th>阶段</th><th>状态</th><th>会话</th><th>追踪编号</th><th>耗时</th><th>时间</th><th>详情</th></tr></thead><tbody>
        {items.map(item => <tr key={item.id}><td>{phases[item.phase] ?? item.phase}</td><td>{item.status}</td><td>{item.conversation_id ?? "旧版提问"}</td><td><button className="audit-trace" title={item.trace_id} onClick={() => { setTrace(item.trace_id); setOffset(0); }}>{item.trace_id.slice(0, 12)}…</button></td><td>{item.duration_ms} ms</td><td>{new Date(item.created_at).toLocaleString("zh-CN")}</td><td><button className="btn-pill ghost sm" disabled={busy} onClick={async () => {
          const target = scope; setBusy(true);
          try { const row = await learningApi.audit(item.id); if (activeScope.current === target) setDetail(row); }
          catch (e) { if (activeScope.current === target) setError(e instanceof Error ? e.message : "加载失败"); }
          finally { if (activeScope.current === target) setBusy(false); }
        }}>查看正文</button></td></tr>)}
      </tbody></table></div>
      {!items.length && !busy && <p className="hint">暂无记录。学生发起新提问后，点击刷新。</p>}
      <div className="application-tabs"><button className="btn-pill ghost sm" disabled={busy || offset === 0} onClick={() => setOffset(Math.max(0, offset - 30))}>上一页</button><span>{Math.floor(offset / 30) + 1} / {Math.max(1, Math.ceil(total / 30))}</span><button className="btn-pill ghost sm" disabled={busy || offset + 30 >= total} onClick={() => setOffset(offset + 30)}>下一页</button></div>
      </div>
      {detail && <section className="panel" style={{ marginTop: 24 }}><h3>记录 #{detail.id} · {phases[detail.phase] ?? detail.phase}</h3><p className="hint">{detail.endpoint || "没有向模型发起请求"}</p>
        {[ ["实际请求参数", detail.request], ["返回内容", detail.response], ["检索、技能与引导配置", detail.context] ].map(([title, value]) => <details key={String(title)} open><summary>{String(title)}</summary><pre className="audit-json">{JSON.stringify(value, null, 2)}</pre></details>)}
      </section>}
    </>}
  </AppShell>;
}

export default function InvocationsPage() { return <AuthGate><InvocationsHome /></AuthGate>; }
