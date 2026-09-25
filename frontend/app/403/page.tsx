"use client";

import { useRouter } from "next/navigation";

export default function ForbiddenPage() {
  const router = useRouter();

  return (
    <div className="centered" style={{ minHeight: "100vh" }}>
      <div className="card" style={{ textAlign: "center", maxWidth: 400 }}>
        <h1 style={{ fontSize: 48, marginBottom: 8 }}>403</h1>
        <p style={{ marginBottom: 24 }}>您无权访问该页面</p>
        <button className="btn" onClick={() => router.replace("/")}>
          返回首页
        </button>
      </div>
    </div>
  );
}
