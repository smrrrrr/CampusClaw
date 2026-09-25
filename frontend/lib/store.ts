"use client";

import { create } from "zustand";

export interface StudentInfo {
  id: number;
  name: string | null;
  class_id: number | null;
}

interface AuthState {
  // 会话
  accessToken: string | null;
  userRole: "teacher" | "student" | null;
  mustChangePassword: boolean;
  isPhoneLogin: boolean;
  currentStudent: StudentInfo | null;
  // 多娃家长才允许显示"切换孩子"
  canSwitchStudent: boolean;
  // 教师任教班级 ID 列表
  teachingClasses: number[] | null;

  // 动作
  setSession: (session: {
    accessToken: string;
    userRole: "teacher" | "student";
    mustChangePassword: boolean;
    isPhoneLogin: boolean;
    currentStudent: StudentInfo | null;
    canSwitchStudent?: boolean;
    teachingClasses?: number[] | null;
  }) => void;
  updateAccessToken: (accessToken: string, mustChangePassword: boolean) => void;
  resetBusinessState: () => void;
  reset: () => void;
}

const EMPTY = {
  accessToken: null as string | null,
  userRole: null as "teacher" | "student" | null,
  mustChangePassword: false,
  isPhoneLogin: false,
  currentStudent: null as StudentInfo | null,
  canSwitchStudent: false,
  teachingClasses: null as number[] | null,
};

export const useAuthStore = create<AuthState>((set) => ({
  ...EMPTY,

  setSession: ({
    accessToken,
    userRole,
    mustChangePassword,
    isPhoneLogin,
    currentStudent,
    canSwitchStudent = false,
    teachingClasses = null,
  }) =>
    set({
      accessToken,
      userRole,
      mustChangePassword,
      isPhoneLogin,
      currentStudent,
      canSwitchStudent,
      teachingClasses,
    }),

  updateAccessToken: (accessToken, mustChangePassword) =>
    set({ accessToken, mustChangePassword }),

  // 多娃切换时调用：清空业务缓存（作业、AI 历史、错题本、班级数据），RBAC 规约要求全量清空后重新拉取
  resetBusinessState: () =>
    set({
      currentStudent: null,
      // 后续业务缓存（作业、AI 历史、错题本）在此一并清空
    }),

  reset: () => set({ ...EMPTY }),
}));
