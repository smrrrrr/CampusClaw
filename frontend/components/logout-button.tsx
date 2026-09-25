"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearRoleCookies } from "@/lib/api";
import { useAuthStore } from "@/lib/store";

export function LogoutButton() {
  const router = useRouter();
  const reset = useAuthStore((s) => s.reset);
  const [loading, setLoading] = useState(false);

  const handleLogout = async () => {
    setLoading(true);
    try {
      await api.logout();
    } catch {
      // 即使后端清除 Cookie 失败，前端仍清除本地状态
    } finally {
      clearRoleCookies();
      reset();
      router.replace("/login");
    }
  };

  return (
    <button
      className="btn"
      style={{ width: "auto", padding: "8px 16px" }}
      onClick={handleLogout}
      disabled={loading}
    >
      {loading ? "退出中…" : "登 出"}
    </button>
  );
}
