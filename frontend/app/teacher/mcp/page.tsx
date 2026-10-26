"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AuthGate } from "@/components/auth-guard";
import { AppShell, TEACHER_NAV } from "@/components/app-layout";
import { ClassSelector } from "@/components/class-selector";
import { LogoutButton } from "@/components/logout-button";
import { mcpApi, type MCPServerDTO, type SkillDTO, type ToolAuditDTO } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

function MCPHome() {
  const router = useRouter();
  const teachingClasses = useAuthStore(s => s.teachingClasses);
  const [classId, setClassId] = useState<number | null>(teachingClasses?.[0] ?? null);
  const activeClass = useRef(classId);
  activeClass.current = classId;
  const [servers, setServers] = useState<MCPServerDTO[]>([]);
  const [skills, setSkills] = useState<SkillDTO[]>([]);
  const [audits, setAudits] = useState<ToolAuditDTO[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [name, setName] = useState("campus-tools");
  const [baseUrl, setBaseUrl] = useState("http://mcp-server:8090");
  const [content, setContent] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [importName, setImportName] = useState("");

  const reload = useCallback(async () => {
    if (classId === null) return;
    const target = classId;
    const [s, k, a] = await Promise.all([mcpApi.servers(target), mcpApi.skills(target), mcpApi.audits(target)]);
    if (activeClass.current !== target) return;
    setServers(s); setSkills(k); setAudits(a.items); setAuditTotal(a.total);
  }, [classId]);

  useEffect(() => {
    setServers([]); setSkills([]); setAudits([]); setContent(""); setEditing(null);
    setMessage(""); setError(""); setLoading(true);
    setImportName("");
    let current = true;
    reload().catch(e => { if (current) setError(e.message); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [reload]);

  const perform = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true); setMessage(""); setError("");
    try { await action(); await reload(); setMessage(success); }
    catch (e) { setError(e instanceof Error ? e.message : "操作失败"); await reload().catch(() => {}); }
    finally { setBusy(false); }
  };

  const template = (tool: string) => {
    const server = servers.find(s => s.connected)?.name ?? name;
    const options: Record<string, [string, string, string]> = {
      formula_hint: ["公式提示", "公式,勾股,速度,密度,牛顿,欧姆,二次方程", "依据公式工具的适用条件指导学生，结合本班资料；不要编造未覆盖的公式。"],
      unit_convert: ["单位换算", "换算,换成,转成,转换为,转为,等于多少,是多少", "使用工具核对单位和量纲；直接报告换算结果，并说明转换关系。"],
      weather_query: ["天气查询", "天气,气温,降雨", "按用户指定城市查询天气，报告匹配地点、日期、时区和来源；未提供城市时先请用户补充。"],
    };
    const [label, keywords, instructions] = options[tool];
    setEditing(null); setEnabled(true);
    setContent(`[名称]\n${label}\n\n[触发词]\n${keywords}\n\n[工具]\n${tool}@${server}\n\n[指令]\n${instructions}`);
  };

  return <AppShell subtitle="智能教学平台 · 教师端" brandMark="T" navItems={TEACHER_NAV} active="mcp" onNavigate={key => router.push(TEACHER_NAV.find(n => n.key === key)?.to ?? "/teacher")}
    headerLeft={<ClassSelector value={classId} onChange={setClassId} />} headerRight={<LogoutButton />} navFoot="本班工具 · 服务端鉴权">
    <div className="page-title"><h2>工具与技能</h2><p>连接本班工具服务，为助手绑定技能，查看真实调用记录。</p></div>
    {error && <div className="error" role="alert">{error}</div>}
    {message && <div className="success" role="status">{message}</div>}
    {classId === null ? <div className="panel">暂无任教班级。</div> : <>
      <section className="panel" style={{ marginBottom: 24 }}>
        <h3>MCP 服务</h3><p className="hint">登记名称和地址；认证令牌由服务端配置，页面不会显示密钥。</p>
        <form onSubmit={e => { e.preventDefault(); void perform(() => mcpApi.register({ class_id: classId, name, base_url: baseUrl }), "服务器已登记，请连接并发现工具。"); }} style={{ display: "flex", gap: 12, alignItems: "end", flexWrap: "wrap", margin: "18px 0" }}>
          <div className="field" style={{ margin: 0 }}><label htmlFor="mcp-name">服务器名称</label><input id="mcp-name" value={name} onChange={e => setName(e.target.value)} pattern="[a-z][a-z0-9-]*" required /></div>
          <div className="field" style={{ margin: 0, flex: 1, minWidth: 250 }}><label htmlFor="mcp-url">Base URL</label><input id="mcp-url" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} required type="url" /></div>
          <button className="btn-pill" disabled={busy || loading}>登记服务</button>
        </form>
        {loading && <p>加载中…</p>}
        {!loading && !servers.length && <p className="hint">本班尚未登记服务。</p>}
        {servers.map(server => <div key={server.id} style={{ borderTop: "1px solid var(--border, #e5e7eb)", padding: "16px 0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <div><strong>{server.name}</strong> <span className={`chip ${server.connected ? "green" : "red"}`}>{server.connected ? "已连接" : "未连接"}</span><p className="hint">{server.base_url} · {server.token_configured ? "服务端令牌已配置" : "服务端尚未配置令牌"}</p></div>
            <button className="btn-pill ghost sm" disabled={busy} onClick={() => void perform(() => server.connected ? mcpApi.disconnect(server.id) : mcpApi.connect(server.id), server.connected ? "已断开，工具缓存已清空。" : "连接成功，已发现工具。")}>{server.connected ? "断开" : "连接并发现工具"}</button>
          </div>
          {server.tools.map(tool => <details key={tool.name} style={{ marginTop: 10 }}><summary><code>{tool.name}@{server.name}</code> — {tool.description}</summary><pre style={{ overflowX: "auto", padding: 12, background: "#f7f8fa" }}>{JSON.stringify(tool.inputSchema, null, 2)}</pre></details>)}
        </div>)}
      </section>

      <section className="panel" style={{ marginBottom: 24 }}>
        <h3>技能文件</h3><p className="hint">上传 UTF-8 编码的 .md / .txt 文件（最多 48KB、12000 字符），预览后保存。触发词命中时应用指导指令，并调用绑定工具；纯指导技能的 [工具] 段落可留空。</p>
        <div className="field" style={{ marginTop: 14 }}><label htmlFor="skill-upload">上传技能文件</label><input id="skill-upload" type="file" accept=".md,.txt,text/plain,text/markdown" disabled={busy || loading} onChange={async e => {
          const file = e.target.files?.[0]; e.target.value = "";
          if (!file) return;
          const target = classId; setBusy(true); setError(""); setMessage("");
          try {
            const preview = await mcpApi.previewSkill(target, file);
            if (activeClass.current === target) { setContent(preview.content); setEditing(null); setEnabled(true); setImportName(file.name); setMessage(`已校验「${preview.name}」，请查看正文并点击保存技能。`); }
          } catch (error) { if (activeClass.current === target) setError(error instanceof Error ? error.message : "上传失败"); }
          finally { setBusy(false); }
        }} />{importName && <p className="hint">已导入：{importName}，尚未保存的内容可在下方编辑。</p>}</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "14px 0" }}>
          <button className="btn-pill ghost sm" disabled={busy} onClick={() => template("formula_hint")}>公式提示模板</button>
          <button className="btn-pill ghost sm" disabled={busy} onClick={() => template("unit_convert")}>单位换算模板</button>
          <button className="btn-pill ghost sm" disabled={busy} onClick={() => template("weather_query")}>天气查询模板</button>
          <button className="btn-pill ghost sm" disabled={busy} onClick={() => {
            setEditing(null); setEnabled(true); setImportName("");
            setContent("[名称]\n审题引导\n\n[触发词]\n不会,思路,怎么做,解题\n\n[工具]\n\n[指令]\n先请学生说出已知条件与要求，再一次只问一个小问题，鼓励学生自己提出下一步思路，不直接给最终答案。");
          }}>纯指导技能模板</button>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>{skills.map(skill => <button className="btn-pill ghost sm" key={skill.id} disabled={busy} onClick={() => { setEditing(skill.id); setContent(skill.content); setEnabled(skill.enabled); setMessage(""); }}>{skill.name} · {skill.enabled ? "启用" : "停用"}</button>)}</div>
        <form onSubmit={e => { e.preventDefault(); void perform(() => mcpApi.saveSkill(editing, { class_id: classId, content, enabled }).then(skill => setEditing(skill.id)), "技能已保存。"); }}>
          <div className="field"><label htmlFor="skill-file">{editing === null ? "新建技能 / 上传预览" : "编辑技能"}</label><textarea id="skill-file" value={content} onChange={e => setContent(e.target.value)} rows={13} maxLength={12000} required placeholder="选择上方模板，或填写 [名称]、[触发词]、[工具]、[指令]" style={{ fontFamily: "monospace" }} /></div>
          <label style={{ display: "block", marginBottom: 14 }}><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} /> 启用此技能</label>
          <button className="btn-pill" disabled={busy || !content.trim()}>保存技能</button>
          <p className="hint">保存后，到「学科应用与模板」为指定学科绑定此技能；通用助手继续使用本班全部启用技能。</p>
          {editing !== null && <button type="button" className="btn-pill ghost" style={{ marginLeft: 10 }} onClick={() => { setEditing(null); setContent(""); }}>新建其他技能</button>}
        </form>
      </section>

      <section className="panel">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}><h3>本班调用审计（{auditTotal} 条）</h3><button className="btn-pill ghost sm" disabled={busy} onClick={() => void perform(reload, "记录已刷新。")}>刷新记录</button></div>
        {!audits.length ? <p className="hint">暂无调用记录。保存技能后，可在学生对话中提问“速度公式是什么”“1 km 转成 m”或“上海明天天气”。</p> : <div className="data-table-wrap" style={{ overflowX: "auto", marginTop: 16 }}><table className="data-table"><thead><tr><th>工具</th><th>状态</th><th>用户</th><th>会话</th><th>耗时</th><th>时间</th><th>摘要</th></tr></thead><tbody>{audits.map(a => <tr key={a.id}><td>{a.tool_ref}</td><td><span className={`chip ${a.status === "ok" ? "green" : "red"}`}>{a.status}</span></td><td>{a.user_id}</td><td>{a.conversation_id}</td><td>{a.duration_ms} ms</td><td style={{ whiteSpace: "nowrap" }}>{new Date(a.created_at + (a.created_at.endsWith("Z") ? "" : "Z")).toLocaleString("zh-CN")}</td><td><details><summary>查看</summary><pre style={{ maxWidth: 360, whiteSpace: "pre-wrap" }}>{a.summary}</pre></details></td></tr>)}</tbody></table></div>}
        <p className="hint" style={{ marginTop: 12 }}>显示最近 50 条。<a href="/api/docs" target="_blank" rel="noreferrer">打开接口文档</a></p>
      </section>
    </>}
  </AppShell>;
}

export default function MCPPage() { return <AuthGate><MCPHome /></AuthGate>; }
