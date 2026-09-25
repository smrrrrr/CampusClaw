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

async function refreshAccessToken(): Promise<boolean> {
  // 并发请求只触发一次刷新
  if (refreshingPromise) return refreshingPromise;

  refreshingPromise = (async () => {
    try {
      const res = await fetch("/api/auth/refresh", {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) return false;
      const data = await res.json();
      useAuthStore
        .getState()
        .updateAccessToken(data.access_token, data.must_change_password);
      if (data.teaching_classes !== undefined) {
        useAuthStore.setState({ teachingClasses: data.teaching_classes });
      }
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
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (token) headers["Authorization"] = `Bearer ${token}`;

    return fetch(path, {
      method: options.method ?? "GET",
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
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

  // --- 教师班级/学生（API 请求不携带 class_id，后端从 JWT teaching_classes 过滤）---
  listClasses: () =>
    apiRequest<{ id: number; name: string }[]>("/api/teacher/classes"),
  listStudents: () =>
    apiRequest<{ items: { id: number; identifier: string; name: string | null; class_id: number | null; class_name: string | null; phone: string | null }[]; total: number }>(
      "/api/teacher/students",
      { method: "GET" },
    ),

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
