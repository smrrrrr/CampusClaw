import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CampusClaw 校园助手",
  description: "CampusClaw 登录与账号体系",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
