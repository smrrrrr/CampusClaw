"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuthStore } from "@/lib/store";

/**
 * 客户端路由守卫：
 * - 未登录 → /login
 * - 密码登录且 must_change_password=true → /change-password
 * - 验证码登录（is_phone_login）跳过强制改密页
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  const accessToken = useAuthStore((s) => s.accessToken);
  const mustChangePassword = useAuthStore((s) => s.mustChangePassword);
  const isPhoneLogin = useAuthStore((s) => s.isPhoneLogin);
  const userRole = useAuthStore((s) => s.userRole);
  const wrongRole =
    ((pathname === "/teacher" || pathname.startsWith("/teacher/")) && userRole !== "teacher") ||
    ((pathname === "/student" || pathname.startsWith("/student/")) && userRole !== "student");
  const needsPasswordChange = mustChangePassword && !isPhoneLogin;
  const ready = !!accessToken && !wrongRole &&
    (pathname === "/change-password" ? needsPasswordChange : !needsPasswordChange);

  useEffect(() => {
    if (!accessToken) {
      router.replace("/login");
      return;
    }
    if (mustChangePassword && !isPhoneLogin && pathname !== "/change-password") {
      router.replace("/change-password");
      return;
    }
    if (
      pathname === "/change-password" &&
      (!mustChangePassword || isPhoneLogin)
    ) {
      router.replace("/");
      return;
    }
    if (wrongRole) router.replace("/403");
  }, [accessToken, mustChangePassword, isPhoneLogin, pathname, router, wrongRole]);

  if (!ready) {
    return <div className="centered">加载中…</div>;
  }

  return <>{children}</>;
}
