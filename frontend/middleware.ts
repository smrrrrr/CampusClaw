import { NextRequest, NextResponse } from "next/server";

/**
 * 路由级权限拦截（middleware.ts）：
 * - /teacher/* 仅 role=teacher 可访问
 * - /student/* 仅 role=student 可访问
 * - 未登录重定向到 /login
 * - 越权重定向到 /403
 *
 * 注意：Access Token 仅存于客户端内存（Zustand），middleware 无法读取。
 * 使用非 HttpOnly 的 role Cookie 辅助路由守卫，后端 API 鉴权仍以 JWT 为准。
 */

const TEACHER_PATH = /^\/teacher(\/|$)/;
const STUDENT_PATH = /^\/student(\/|$)/;

// 不需要守卫的路径
const PUBLIC_PATHS = ["/login", "/change-password", "/403", "/api"];

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // 公共路径放行
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const role = req.cookies.get("cc_role")?.value;
  const hasToken = req.cookies.get("cc_has_token")?.value === "1";

  // 未登录 → /login
  if (!hasToken) {
    return NextResponse.redirect(new URL("/login", req.url));
  }

  // 角色校验
  if (TEACHER_PATH.test(pathname) && role !== "teacher") {
    return NextResponse.redirect(new URL("/403", req.url));
  }
  if (STUDENT_PATH.test(pathname) && role !== "student") {
    return NextResponse.redirect(new URL("/403", req.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
