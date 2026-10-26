"use client";

import { useEffect, useState } from "react";
import { clearRoleCookies, refreshAccessToken } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

/** 页面守卫和业务请求必须等待 HttpOnly Cookie 恢复会话后再执行。 */
export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    async function restoreSession() {
      if (!useAuthStore.getState().accessToken) {
        const restored = await refreshAccessToken();
        if (!restored) {
          useAuthStore.getState().reset();
          clearRoleCookies();
        }
      }
      if (active) setReady(true);
    }
    void restoreSession();
    return () => { active = false; };
  }, []);

  return ready ? <>{children}</> : <div className="centered">正在恢复登录状态…</div>;
}
