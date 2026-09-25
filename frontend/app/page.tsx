"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/store";

export default function HomePage() {
  const router = useRouter();

  useEffect(() => {
    const { accessToken, userRole, mustChangePassword, isPhoneLogin } =
      useAuthStore.getState();
    if (!accessToken) {
      router.replace("/login");
    } else if (mustChangePassword && !isPhoneLogin) {
      router.replace("/change-password");
    } else {
      router.replace(userRole === "teacher" ? "/teacher" : "/student");
    }
  }, [router]);

  return <div className="centered">加载中…</div>;
}
