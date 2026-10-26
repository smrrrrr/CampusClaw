"use client";

import type { ReactNode } from "react";

export interface NavItem {
  key: string;
  label: string;
  icon: string;
  to?: string;
  children?: NavItem[];
}

const ICONS: Record<string, ReactNode> = {
  home: <path d="M3 10.5 12 3l9 7.5M5 9v11h5v-6h4v6h5V9" fill="none" stroke="currentColor" strokeWidth={1.8} />,
  doc: <path d="M7 3h7l4 4v14H7zM14 3v4h4" fill="none" stroke="currentColor" strokeWidth={1.8} />,
  robot: (
    <g fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round">
      <rect x="5" y="7" width="14" height="13" rx="3" />
      <path d="M12 7V4" />
      <path d="M9 11h.01M15 11h.01M9.5 16a3.5 3.5 0 0 0 5 0" />
    </g>
  ),
  chat: <path d="M4 4h16v12H8l-4 4V4z" fill="none" stroke="currentColor" strokeWidth={1.8} />,
  upload: <path d="M12 16V4m0 0-4 4m4-4 4 4M5 20h14" fill="none" stroke="currentColor" strokeWidth={1.8} />,
  log: <path d="M4 20V10m5 10V4m5 16v-7m5 7V7" fill="none" stroke="currentColor" strokeWidth={1.8} />,
  tools: (
    <path
      d="M14.7 6.3c1-.3 1.6-.8 2.1-1.5l-2.1-2.1C14 3.2 13.5 3.8 13.2 4.8M21 12c0 3.3-2.7 6-6 6H9c-3.3 0-6-2.7-6-6s2.7-6 6-6h6c.9 0 1.7.2 2.4.6M10 10.5h.01M14 13.5h.01"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
    />
  ),
  audit: <path d="M4 20V10m5 10V4m5 16v-7m5 7V7" fill="none" stroke="currentColor" strokeWidth={1.8} />,
};

/* 教师端统一导航：顶级菜单对齐，上传资料作为「讲义管理」的子功能 */
export const TEACHER_NAV: NavItem[] = [
  { key: "home", label: "本班首页", icon: "home", to: "/teacher" },
  {
    key: "materials",
    label: "讲义管理",
    icon: "doc",
    to: "/materials",
    children: [{ key: "upload", label: "上传资料", icon: "upload", to: "/teacher/upload" }],
  },
  { key: "agent", label: "助手配置", icon: "robot", to: "/teacher" },
  { key: "applications", label: "学科应用与模板", icon: "robot", to: "/teacher/applications" },
  { key: "mcp", label: "工具与技能", icon: "tools", to: "/teacher/mcp" },
  { key: "invocations", label: "调用验证", icon: "log", to: "/teacher/invocations" },
  { key: "tools", label: "作业与改分", icon: "tools", to: "/teacher" },
  { key: "audit", label: "审计与统计", icon: "audit", to: "/teacher" },
];

function isParentActive(item: NavItem, active: string): boolean {
  if (item.key === active) return true;
  return !!item.children?.some((c) => c.key === active);
}

export function AppShell({
  brandMark = "C",
  subtitle,
  navItems,
  active,
  onNavigate,
  headerLeft,
  headerRight,
  navFoot = "演示项目 · 数据均为 mock",
  children,
}: {
  brandMark?: string;
  subtitle: string;
  navItems: NavItem[];
  active: string;
  onNavigate: (key: string) => void;
  headerLeft?: ReactNode;
  headerRight?: ReactNode;
  navFoot?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-brand">
          <div className="b-mark">{brandMark}</div>
          <h1>CampusClaw</h1>
          <p>{subtitle}</p>
        </div>
        <nav className="app-nav">
          <div className="sec">导航</div>
          {navItems.map((it) => {
            const parentActive = isParentActive(it, active);
            return (
              <div key={it.key} className="nav-group">
                <button
                  className={`nav-item${parentActive ? " active" : ""}`}
                  onClick={() => onNavigate(it.key)}
                >
                  {ICONS[it.icon] ?? null}
                  <span>{it.label}</span>
                </button>
                {it.children && parentActive && (
                  <div className="nav-sub">
                    {it.children.map((c) => (
                      <button
                        key={c.key}
                        className={`nav-item sub${active === c.key ? " active" : ""}`}
                        onClick={() => onNavigate(c.key)}
                      >
                        {ICONS[c.icon] ?? null}
                        <span>{c.label}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
        <div className="footer">{navFoot}</div>
      </aside>
      <div className="app-main">
        <header className="app-headerbar">
          <div className="hdr-left">{headerLeft ?? <span className="status-dot" />}</div>
          <div className="hdr-right">{headerRight}</div>
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
}
