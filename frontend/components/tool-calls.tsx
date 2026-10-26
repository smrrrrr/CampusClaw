import type { ToolCallDTO } from "@/lib/api";

export function ToolCalls({ calls }: { calls: ToolCallDTO[] }) {
  if (!calls.length) return null;
  const labels = { ok: "成功", error: "失败", denied: "已拒绝", needs_input: "请补充地点" };
  return <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "10px 0" }} aria-label="工具调用记录">
    {calls.map((call, i) => <span key={`${call.tool_ref}-${i}`} title={call.summary} className={`chip ${call.status === "ok" ? "green" : call.status === "needs_input" ? "" : "red"}`}>
      {call.tool_ref} · {labels[call.status] ?? call.status}
    </span>)}
  </div>;
}
