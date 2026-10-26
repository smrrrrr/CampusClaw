"use client";

import { useAuthStore } from "./store";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  // 为 true 时 401 不触发自动刷新（登录/刷新接口本身）
  skipAuthRefresh?: boolean;
}

let refreshingPromise: Promise<boolean> | null = null;

export async function refreshAccessToken(): Promise<boolean> {
  // 并发请求只触发一次刷新
  if (refreshingPromise) return refreshingPromise;

  refreshingPromise = (async () => {
    try {
      const res = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) return false;
      const data: RefreshDTO = await res.json();
      useAuthStore.getState().setSession({
        accessToken: data.access_token,
        userRole: data.role,
        mustChangePassword: data.must_change_password,
        isPhoneLogin: data.is_phone_login,
        currentStudent: data.role === "student" ? {
          id: data.user.id,
          name: data.user.name,
          class_id: data.user.class_id,
        } : null,
        canSwitchStudent: data.can_switch_student,
        teachingClasses: data.user.teaching_classes ?? null,
      });
      setRoleCookies(data.role);
      return true;
    } catch {
      return false;
    } finally {
      refreshingPromise = null;
    }
  })();

  return refreshingPromise;
}

export async function apiRequest<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const doFetch = (): Promise<Response> => {
    const token = useAuthStore.getState().accessToken;
    const headers: Record<string, string> = {};
    const multipart = typeof FormData !== "undefined" && options.body instanceof FormData;
    if (options.body !== undefined && !multipart) headers["Content-Type"] = "application/json";
    if (token) headers["Authorization"] = `Bearer ${token}`;

    return fetch(path, {
      method: options.method ?? "GET",
      headers,
      body: multipart ? options.body as FormData : options.body !== undefined ? JSON.stringify(options.body) : undefined,
      credentials: "include",
    });
  };

  let res = await doFetch();

  // Access Token 过期：自动刷新后重试一次
  if (res.status === 401 && !options.skipAuthRefresh) {
    const ok = await refreshAccessToken();
    if (ok) {
      res = await doFetch();
    } else {
      useAuthStore.getState().reset();
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
      throw new ApiError(401, "登录已失效，请重新登录");
    }
  }

  if (!res.ok) {
    let detail = "请求失败";
    try {
      const data = await res.json();
      detail = data.detail ?? detail;
    } catch {
      // 非 JSON 错误体
    }
    throw new ApiError(res.status, detail);
  }

  // 204 / 空响应
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- 类型定义（与后端 schemas 对齐） ---

export interface UserInfoDTO {
  id: number;
  role: "teacher" | "student";
  name: string | null;
  class_id: number | null;
  must_change_password: boolean;
  teaching_classes?: number[] | null;
}

export interface TokenDTO {
  access_token: string;
  token_type: string;
  must_change_password: boolean;
  role: "teacher" | "student";
  user: UserInfoDTO;
}

export interface RefreshDTO extends TokenDTO {
  is_phone_login: boolean;
  can_switch_student: boolean;
}

/** 设置/清除用于 middleware 路由守卫的辅助 Cookie（非 HttpOnly，仅前端路由用）。 */
export function setRoleCookies(role: "teacher" | "student") {
  document.cookie = `cc_role=${role}; path=/; max-age=${7 * 24 * 60 * 60}`;
  document.cookie = "cc_has_token=1; path=/; max-age=" + 7 * 24 * 60 * 60;
}

export function clearRoleCookies() {
  document.cookie = "cc_role=; path=/; max-age=0";
  document.cookie = "cc_has_token=; path=/; max-age=0";
}

export interface StudentBriefDTO {
  id: number;
  name: string | null;
  class_id: number | null;
  class_name: string | null;
}

export interface VerifyCodeDTO {
  access_token?: string;
  token_type?: string;
  must_change_password?: boolean;
  role?: "teacher" | "student";
  user?: UserInfoDTO;
  temp_token?: string;
  students?: StudentBriefDTO[];
  message?: string;
}

export const api = {
  login: (identifier: string, password: string) =>
    apiRequest<TokenDTO>("/api/auth/login", {
      method: "POST",
      body: { identifier, password },
      skipAuthRefresh: true,
    }),

  sendCode: (phone: string) =>
    apiRequest<{ message: string; code?: string }>("/api/auth/send-code", {
      method: "POST",
      body: { phone },
      skipAuthRefresh: true,
    }),

  verifyCode: (phone: string, code: string) =>
    apiRequest<VerifyCodeDTO>("/api/auth/verify-code", {
      method: "POST",
      body: { phone, code },
      skipAuthRefresh: true,
    }),

  selectStudent: (tempToken: string, studentId: number) =>
    apiRequest<TokenDTO>("/api/auth/select-student", {
      method: "POST",
      body: { temp_token: tempToken, student_id: studentId },
      skipAuthRefresh: true,
    }),

  switchStudent: () => apiRequest<VerifyCodeDTO>("/api/auth/switch-student", { method: "POST" }),

  changePassword: (oldPassword: string, newPassword: string) =>
    apiRequest<TokenDTO>("/api/auth/change-password", {
      method: "POST",
      body: { old_password: oldPassword, new_password: newPassword },
    }),

  logout: () =>
    apiRequest<{ message: string }>("/api/auth/logout", { method: "POST" }),

  // --- 学生 AI 提问 ---
  askAI: (question: string) =>
    apiRequest<AIAnswerResponse>(
      "/api/student/ai-question",
      { method: "POST", body: { question } },
    ),
  getAIHistory: () =>
    apiRequest<AIHistoryItem[]>("/api/student/ai-history", { method: "GET" }),
  deleteAIHistory: (id: number) =>
    apiRequest<{ ok: boolean }>(`/api/student/ai-history/${id}`, { method: "DELETE" }),

  // --- 教师班级/学生（API 请求不携带 class_id，后端从 JWT teaching_classes 过滤）---
  listClasses: () =>
    apiRequest<{ id: number; name: string }[]>("/api/teacher/classes"),
  listStudents: () =>
    apiRequest<{ items: { id: number; identifier: string; name: string | null; class_id: number | null; class_name: string | null; phone: string | null }[]; total: number }>(
      "/api/teacher/students",
      { method: "GET" },
    ),
  resetStudentPassword: (studentId: number) =>
    apiRequest<{ message: string; initial_password: string }>(
      "/api/teacher/reset-password",
      { method: "POST", body: { student_id: studentId } },
    ),

  // --- AI 助手配置（教师按班级）---
  getAgentConfig: (classId: number) =>
    apiRequest<AgentConfigDTO>(`/api/teacher/agent-config?class_id=${classId}`),
  saveAgentConfig: (payload: { class_id: number; system_prompt: string; tutor_enabled: boolean }) =>
    apiRequest<AgentConfigDTO>("/api/teacher/agent-config", { method: "PUT", body: payload }),
  getAgentDefaultPrompt: () =>
    apiRequest<{ system_prompt: string; tutor_skill_prompt: string }>(
      "/api/teacher/agent-config/default-prompt",
    ),

  // --- AI 助手多轮会话（学生）---
  createConversation: (title?: string, applicationId?: number | null) =>
    apiRequest<ConversationItemDTO>("/api/student/conversations", {
      method: "POST",
      body: { title: title ?? "新对话", application_id: applicationId ?? null },
    }),
  listConversations: () =>
    apiRequest<ConversationItemDTO[]>("/api/student/conversations"),
  getConversationMessages: (id: number) =>
    apiRequest<ConversationMessageDTO[]>(`/api/student/conversations/${id}/messages`),
  deleteConversation: (id: number) =>
    apiRequest<{ ok: boolean }>(`/api/student/conversations/${id}`, { method: "DELETE" }),

  // --- 材料 ---
  uploadMaterial: (
    formData: FormData,
    onProgress?: (loaded: number, total: number) => void,
  ) =>
    new Promise<{ id: number; filename: string; file_type: string; file_size: number; class_id: number; is_indexed: boolean; created_at: string; message: string }>(
      (resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/teacher/upload-material");
        const token = useAuthStore.getState().accessToken;
        if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
        xhr.withCredentials = true;
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable && onProgress) {
            onProgress(e.loaded, e.total);
          }
        };
        xhr.onload = () => {
          if (xhr.status === 401) {
            refreshAccessToken().then((ok) => {
              if (ok) {
                const newToken = useAuthStore.getState().accessToken;
                if (newToken) xhr.setRequestHeader("Authorization", `Bearer ${newToken}`);
                // 重试
                xhr.open("POST", "/api/teacher/upload-material");
                xhr.setRequestHeader("Authorization", `Bearer ${newToken}`);
                xhr.send(formData);
              } else {
                reject(new ApiError(401, "登录已失效，请重新登录"));
              }
            });
            return;
          }
          if (xhr.status >= 400) {
            let detail = "上传失败";
            try {
              detail = JSON.parse(xhr.responseText).detail ?? detail;
            } catch {
              // 非 JSON
            }
            reject(new ApiError(xhr.status, detail));
            return;
          }
          resolve(JSON.parse(xhr.responseText));
        };
        xhr.onerror = () => reject(new ApiError(0, "网络中断，请重试"));
        xhr.send(formData);
      },
    ),

  listMaterials: (params?: { class_id?: number; search?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.class_id !== undefined) qs.set("class_id", String(params.class_id));
    if (params?.search) qs.set("search", params.search);
    if (params?.limit !== undefined) qs.set("limit", String(params.limit));
    if (params?.offset !== undefined) qs.set("offset", String(params.offset));
    const q = qs.toString();
    return apiRequest<{
      items: MaterialItemDTO[];
      total: number;
    }>(q ? `/api/materials?${q}` : "/api/materials");
  },

  reindexMaterial: (materialId: number) =>
    apiRequest<{ id: number; is_indexed: boolean; message: string }>(
      `/api/teacher/materials/${materialId}/reindex`,
      { method: "POST" },
    ),

  deleteMaterial: (materialId: number) =>
    apiRequest<{ id: number; message: string }>(
      `/api/teacher/materials/${materialId}`,
      { method: "DELETE" },
    ),

  materialDownloadUrl: (materialId: number) => `/api/materials/${materialId}/download`,
  materialPreviewUrl: (materialId: number) => `/api/materials/${materialId}/preview`,
};

export interface MaterialItemDTO {
  id: number;
  class_id: number;
  uploader_id: number;
  filename: string;
  file_type: string;
  file_size: number;
  description: string | null;
  tags: string[];
  is_indexed: boolean;
  created_at: string;
  class_name: string | null;
}

// AI 回答溯源（add-rag-search）
export interface AnswerCitation {
  material_id: number;
  filename: string;
  chunk_index: number;
  excerpt: string;
  score: number;
}

export interface AIAnswerResponse {
  id: number;
  answer: string;
  remaining: number;
  citations: AnswerCitation[];
}

export interface AIHistoryItem {
  id: number;
  question: string;
  answer: string;
  created_at: string;
}

// --- AI 助手配置与会话（多轮 agent）---

export interface AgentConfigDTO {
  class_id: number;
  system_prompt: string;
  tutor_enabled: boolean;
}

export interface ConversationItemDTO {
  id: number;
  title: string;
  updated_at: string;
  application_id?: number | null;
}

export interface ConversationMessageDTO {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: AnswerCitation[];
  tool_calls?: ToolCallDTO[];
  created_at: string;
}

export interface ChatDoneData {
  answer: string;
  citations: AnswerCitation[];
  remaining: number;
  tool_calls: ToolCallDTO[];
}

export interface ToolCallDTO {
  tool_ref: string;
  status: "ok" | "error" | "denied" | "needs_input";
  skill?: string;
  duration_ms?: number;
  summary?: string;
}

export interface MCPServerDTO {
  id: number; class_id: number; name: string; base_url: string;
  connected: boolean; token_configured: boolean;
  tools: { name: string; description: string; inputSchema: Record<string, unknown> }[];
}

export interface SkillDTO {
  id: number; class_id: number; name: string; content: string; enabled: boolean;
  keywords: string[]; tools: string[];
}

export interface ToolAuditDTO {
  id: number; class_id: number; user_id: number; conversation_id: number;
  tool_ref: string; status: string; duration_ms: number; summary: string; created_at: string;
}

export const mcpApi = {
  previewSkill: (classId: number, file: File) => {
    const body = new FormData();
    body.append("class_id", String(classId)); body.append("file", file);
    return apiRequest<{ name: string; content: string; keywords: string[]; tools: string[] }>("/api/teacher/skills/preview", { method: "POST", body });
  },
  servers: (classId: number) => apiRequest<MCPServerDTO[]>(`/api/teacher/mcp-servers?class_id=${classId}`),
  register: (body: { class_id: number; name: string; base_url: string }) => apiRequest<MCPServerDTO>("/api/teacher/mcp-servers", { method: "POST", body }),
  connect: (id: number) => apiRequest<MCPServerDTO>(`/api/teacher/mcp-servers/${id}/connect`, { method: "POST" }),
  disconnect: (id: number) => apiRequest<MCPServerDTO>(`/api/teacher/mcp-servers/${id}/disconnect`, { method: "POST" }),
  skills: (classId: number) => apiRequest<SkillDTO[]>(`/api/teacher/skills?class_id=${classId}`),
  saveSkill: (id: number | null, body: { class_id: number; content: string; enabled: boolean }) => apiRequest<SkillDTO>(id === null ? "/api/teacher/skills" : `/api/teacher/skills/${id}`, { method: id === null ? "POST" : "PUT", body }),
  audits: (classId: number) => apiRequest<{ items: ToolAuditDTO[]; total: number }>(`/api/teacher/tool-audits?class_id=${classId}`),
};

export interface ApplicationDTO {
  id: number; class_id: number; subject: string; name: string; system_prompt: string;
  tutor_enabled: boolean; material_ids: number[] | null; skill_ids: number[] | null;
}
export type StudentApplicationDTO = Pick<ApplicationDTO, "id" | "name" | "subject" | "tutor_enabled">;
export interface PromptTemplateDTO { id: string; name: string; content: string; builtin: boolean; }
export interface InvocationDTO {
  id: number; trace_id: string; class_id: number; user_id: number; conversation_id: number | null;
  application_id: number | null; phase: string; endpoint: string; status: string; duration_ms: number; created_at: string;
  request?: unknown; response?: unknown; context?: unknown;
}
export const learningApi = {
  studentApplications: () => apiRequest<StudentApplicationDTO[]>("/api/student/applications"),
  applications: (classId: number) => apiRequest<ApplicationDTO[]>(`/api/teacher/applications?class_id=${classId}`),
  saveApplication: (app: ApplicationDTO) => apiRequest<ApplicationDTO>(`/api/teacher/applications/${app.id}`, { method: "PUT", body: app }),
  templates: (classId: number) => apiRequest<PromptTemplateDTO[]>(`/api/teacher/prompt-templates?class_id=${classId}`),
  saveTemplate: (id: string | null, body: { class_id: number; name: string; content: string }) =>
    apiRequest<PromptTemplateDTO>(id === null ? "/api/teacher/prompt-templates" : `/api/teacher/prompt-templates/${id}`, { method: id === null ? "POST" : "PUT", body }),
  deleteTemplate: (id: string) => apiRequest<void>(`/api/teacher/prompt-templates/${id}`, { method: "DELETE" }),
  audits: (params: URLSearchParams) => apiRequest<{ items: InvocationDTO[]; total: number }>(`/api/teacher/invocation-audits?${params}`),
  audit: (id: number) => apiRequest<InvocationDTO>(`/api/teacher/invocation-audits/${id}`),
  exportAudits: (params: URLSearchParams) => apiRequest<unknown>(`/api/teacher/invocation-audits/export?${params}`),
};

interface ChatStreamCallbacks {
  onMeta?: (calls: ToolCallDTO[]) => void;
  onDelta?: (text: string) => void;
  onDone?: (data: ChatDoneData) => void;
  onError?: (message: string) => void;
}

/** 向某会话发起流式提问；通过 fetch 读取 SSE，按事件分发 delta / done / error。 */
export async function streamChat(
  conversationId: number,
  question: string,
  cb: ChatStreamCallbacks,
): Promise<void> {
  const doFetch = (): Promise<Response> => {
    const token = useAuthStore.getState().accessToken;
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return fetch(`/api/student/conversations/${conversationId}/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify({ question }),
      credentials: "include",
    });
  };

  let res = await doFetch();
  if (res.status === 401) {
    const ok = await refreshAccessToken();
    if (ok) {
      res = await doFetch();
    } else {
      useAuthStore.getState().reset();
      cb.onError?.("登录已失效，请重新登录");
      return;
    }
  }
  if (!res.status) throw new ApiError(0, "网络中断");

  if (!res.ok || !res.body) {
    let detail = "提问失败";
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // 忽略
    }
    cb.onError?.(detail);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (raw: string) => {
    for (const line of raw.split("\n")) {
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        const evt = JSON.parse(payload);
        if (evt.type === "delta") cb.onDelta?.(evt.content ?? "");
        else if (evt.type === "meta") cb.onMeta?.(evt.tool_calls ?? []);
        else if (evt.type === "done")
          cb.onDone?.({ answer: evt.answer ?? "", citations: evt.citations ?? [], remaining: evt.remaining ?? 0, tool_calls: evt.tool_calls ?? [] });
        else if (evt.type === "error") cb.onError?.(evt.message ?? "AI 响应异常");
      } catch {
        // 忽略非 JSON 的 SSE 行
      }
    }
  };

  try {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // SSE 事件以空行分隔；按每个完整事件处理以支持跨 chunk 的半行
      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        dispatch(chunk);
      }
    }
    if (buffer) dispatch(buffer);
  } catch {
    cb.onError?.("网络中断，请重试");
  }
}
