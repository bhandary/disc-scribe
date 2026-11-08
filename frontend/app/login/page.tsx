"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Disc3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { getToken } from "@/lib/session";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("error")) {
      setError("Google sign-in did not finish. Try again.");
    }
    if (getToken()) router.replace("/");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-6 rounded-lg border border-white/10 glass p-8 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg bg-gradient-to-br from-vinyl-gold to-amber-600 shadow-lg">
          <Disc3 className="h-7 w-7 text-vinyl-obsidian" />
        </div>
        <div className="space-y-2">
          <h1 className="text-4xl">DiscVault AI</h1>
          <p className="text-sm text-muted-foreground">Sign in to open your shelf.</p>
        </div>
        {error && <p className="text-sm text-red-700">{error}</p>}
        <Button asChild className="w-full">
          <a href={api.googleLoginUrl}>Sign in with Google</a>
        </Button>
      </div>
    </div>
  );
}
