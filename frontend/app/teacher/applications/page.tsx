"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthGate } from "@/components/auth-guard";
import { AppShell, TEACHER_NAV } from "@/components/app-layout";
import { ClassSelector } from "@/components/class-selector";
import { LogoutButton } from "@/components/logout-button";
import { api, learningApi, mcpApi, type ApplicationDTO, type MaterialItemDTO, type PromptTemplateDTO, type SkillDTO } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

function Bindings({ title, ids, items, onChange }: { title: string; ids: number[] | null; items: { id: number; label: string }[]; onChange: (ids: number[] | null) => void }) {
  return <fieldset className="binding-box"><legend>{title}</legend>
    <label><input type="checkbox" checked={ids === null} onChange={e => onChange(e.target.checked ? null : [])} /> 使用本班全部{title}（包括后续新增）</label>
    {ids !== null && <><p className="hint">勾选要绑定的项目；全部不选表示不使用{title}。</p>
      <div className="binding-options">{items.length ? items.map(item => <label key={item.id}><input type="checkbox" checked={ids.includes(item.id)} onChange={e => onChange(e.target.checked ? [...ids, item.id] : ids.filter(id => id !== item.id))} /> {item.label}</label>) : <p className="hint">本班暂无{title}。</p>}</div></>}
  </fieldset>;
}

function ApplicationsHome() {
  const router = useRouter();
  const classes = useAuthStore(s => s.teachingClasses);
  const [classId, setClassId] = useState<number | null>(classes?.[0] ?? null);
  const activeClass = useRef(classId); activeClass.current = classId;
  const [apps, setApps] = useState<ApplicationDTO[]>([]);
  const [draft, setDraft] = useState<ApplicationDTO | null>(null);
  const [materials, setMaterials] = useState<MaterialItemDTO[]>([]);
  const [skills, setSkills] = useState<SkillDTO[]>([]);
  const [templates, setTemplates] = useState<PromptTemplateDTO[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [templateName, setTemplateName] = useState("");
  const [templateContent, setTemplateContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (classId === null) return;
    let alive = true;
    setLoading(true); setError(""); setMessage(""); setDraft(null); setApps([]); setTemplates([]); setMaterials([]); setSkills([]);
    setTemplateId(null); setTemplateName(""); setTemplateContent("");
    const allMaterials = async () => {
      const rows: MaterialItemDTO[] = [];
      let total = 0;
      do {
        const page = await api.listMaterials({ class_id: classId, limit: 200, offset: rows.length });
        rows.push(...page.items); total = page.total;
        if (!page.items.length) break;
      } while (rows.length < total);
      return rows;
    };
    Promise.all([learningApi.applications(classId), learningApi.templates(classId), allMaterials(), mcpApi.skills(classId)])
      .then(([a, t, m, s]) => { if (alive) { setApps(a); setDraft(a[0] ?? null); setTemplates(t); setMaterials(m); setSkills(s); } })
      .catch(e => { if (alive) setError(e.message); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [classId]);

  const action = async (work: (target: number) => Promise<void>, success: string) => {
    if (classId === null) return;
    const target = classId;
    setBusy(true); setError(""); setMessage("");
    try { await work(target); if (activeClass.current === target) setMessage(success); }
    catch (e) { if (activeClass.current === target) setError(e instanceof Error ? e.message : "操作失败"); }
    finally { setBusy(false); }
  };
  const chooseTemplate = (template: PromptTemplateDTO) => {
    setTemplateId(template.builtin ? null : template.id); setTemplateName(template.name); setTemplateContent(template.content);
  };

  return <AppShell subtitle="智能教学平台 · 教师端" navItems={TEACHER_NAV} active="applications"
    onNavigate={key => router.push(TEACHER_NAV.find(n => n.key === key)?.to ?? "/teacher")}
    headerLeft={<ClassSelector value={classId} onChange={setClassId} />} headerRight={<LogoutButton />} navFoot="按学科配置 · 启发学生思考">
    <div className="page-title"><h2>学科应用与模板</h2><p>为数学、物理、英语助手分别配置教学方式、知识资料和技能。</p></div>
    {error && <div className="error" role="alert">{error}</div>}{message && <div className="success" role="status">{message}</div>}
    {loading ? <p>加载中…</p> : classId === null ? <p>暂无任教班级。</p> : <>
      <div className="application-tabs">{apps.map(app => <button key={app.id} className={`btn-pill ${draft?.id === app.id ? "" : "ghost"}`} disabled={busy} onClick={() => { setDraft(app); setMessage(""); }}>{app.name}</button>)}</div>
      {draft && <form className="panel" onSubmit={e => { e.preventDefault(); void action(async target => {
        const saved = await learningApi.saveApplication(draft);
        if (activeClass.current === target) { setDraft(saved); setApps(rows => rows.map(a => a.id === saved.id ? saved : a)); }
      }, "应用已保存，新提问将使用当前配置。"); }}>
        <h3>{draft.name}</h3>
        <div className="field"><label htmlFor="application-name">应用名称</label><input id="application-name" maxLength={128} required value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></div>
        <label><input type="checkbox" checked={draft.tutor_enabled} onChange={e => setDraft({ ...draft, tutor_enabled: e.target.checked })} /> 开启解题引导，鼓励学生独立思考</label>
        <p className="hint">开启后会屏蔽下方自定义提示词，使用内置的学科引导规则；关闭后才使用自定义提示词。</p>
        <div className="field"><label htmlFor="application-template">选用提示词模板</label><select id="application-template" value="" onChange={e => { const t = templates.find(t => t.id === e.target.value); if (t) setDraft({ ...draft, system_prompt: t.content }); }}><option value="">选择模板并填入下方</option>{templates.map(t => <option key={t.id} value={t.id}>{t.builtin ? "内置 · " : "自定义 · "}{t.name}</option>)}</select></div>
        <div className="field"><label htmlFor="application-prompt">自定义提示词{draft.tutor_enabled ? "（当前被引导模式屏蔽）" : ""}</label><textarea id="application-prompt" rows={7} maxLength={12000} value={draft.system_prompt} onChange={e => setDraft({ ...draft, system_prompt: e.target.value })} /></div>
        <div className="binding-grid">
          <Bindings title="知识资料" ids={draft.material_ids} items={materials.map(m => ({ id: m.id, label: `${m.filename}${m.is_indexed ? "" : "（尚未索引）"}` }))} onChange={ids => setDraft({ ...draft, material_ids: ids })} />
          <Bindings title="技能" ids={draft.skill_ids} items={skills.map(s => ({ id: s.id, label: `${s.name}${s.enabled ? "" : "（已停用）"}` }))} onChange={ids => setDraft({ ...draft, skill_ids: ids })} />
        </div>
        <p className="hint">新学科应用默认不绑定资料和技能，请按学科勾选。技能还需启用且命中触发词才会执行。<Link href="/teacher/mcp">上传或管理技能</Link></p>
        <button className="btn-pill" disabled={busy}>保存应用</button>
      </form>}
      <section className="panel" style={{ marginTop: 24 }}><h3>提示词模板库</h3><p className="hint">内置模板可另存为自定义模板。将模板应用到助手后，后续编辑模板不会自动覆盖已保存的应用配置。</p>
        <div className="application-tabs">{templates.map(t => <button key={t.id} className="btn-pill ghost sm" disabled={busy} onClick={() => chooseTemplate(t)}>{t.builtin ? "内置 · " : ""}{t.name}</button>)}</div>
        <form onSubmit={e => { e.preventDefault(); void action(async target => {
          const saved = await learningApi.saveTemplate(templateId, { class_id: target, name: templateName, content: templateContent });
          const rows = await learningApi.templates(target);
          if (activeClass.current === target) { setTemplateId(saved.id); setTemplates(rows); }
        }, "模板已保存。"); }}>
          <div className="field"><label htmlFor="template-name">模板名称</label><input id="template-name" required maxLength={128} value={templateName} onChange={e => setTemplateName(e.target.value)} /></div>
          <div className="field"><label htmlFor="template-content">模板内容</label><textarea id="template-content" required maxLength={12000} rows={6} value={templateContent} onChange={e => setTemplateContent(e.target.value)} /></div>
          <div className="application-tabs"><button className="btn-pill" disabled={busy}>{templateId ? "保存模板修改" : "保存新模板"}</button>
            <button type="button" className="btn-pill ghost" disabled={busy} onClick={() => { setTemplateId(null); setTemplateName(""); setTemplateContent(""); }}>新建模板</button>
            {templateId && <button type="button" className="btn-pill ghost" disabled={busy} onClick={() => void action(async target => {
              await learningApi.deleteTemplate(templateId); const rows = await learningApi.templates(target);
              if (activeClass.current === target) { setTemplates(rows); setTemplateId(null); setTemplateName(""); setTemplateContent(""); }
            }, "模板已删除，已保存的应用提示词不受影响。")}>删除模板</button>}
          </div>
        </form>
      </section>
    </>}
  </AppShell>;
}

export default function ApplicationsPage() { return <AuthGate><ApplicationsHome /></AuthGate>; }
