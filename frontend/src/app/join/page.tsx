"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { accountsApi, type InvitePreview } from "@/lib/api/accounts";
import { ApiError } from "@/lib/api/client";
import { roleLabel } from "@/lib/roles";

function JoinContent() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") ?? "";
  const { me, loading, refresh } = useAuth();
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("В ссылке нет токена приглашения.");
      return;
    }
    accountsApi
      .previewInvite(token)
      .then(setPreview)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : "Не удалось открыть приглашение"),
      );
  }, [token]);

  const accept = async () => {
    setPending(true);
    setError(null);
    try {
      await accountsApi.acceptInvite(token);
      await refresh();
      router.replace("/dashboard");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось принять приглашение");
    } finally {
      setPending(false);
    }
  };

  if (loading || (!preview && !error)) {
    return <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />;
  }

  if (error || !preview) {
    return (
      <>
        <h1 className="text-xl font-bold">Приглашение недоступно</h1>
        <p className="mt-2 text-sm text-muted-foreground">{error}</p>
      </>
    );
  }

  return (
    <>
      <h1 className="text-xl font-bold">Приглашение в {preview.organization_name}</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Роль: <span className="font-medium text-foreground">{roleLabel(preview.role)}</span>
        {preview.email ? (
          <>
            {" "}
            · для <span className="font-medium text-foreground">{preview.email}</span>
          </>
        ) : null}
      </p>
      {!preview.valid ? (
        <p className="mt-4 text-sm text-destructive">{preview.reason}</p>
      ) : me ? (
        <div className="mt-6 space-y-3">
          <p className="text-sm">
            Вы вошли как <span className="font-medium">{me.email}</span>.
          </p>
          <Button className="w-full" onClick={accept} disabled={pending}>
            {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            Принять приглашение
          </Button>
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          <Button className="w-full" asChild>
            <Link href={`/register?invite=${encodeURIComponent(token)}`}>Создать аккаунт</Link>
          </Button>
          <Button variant="outline" className="w-full" asChild>
            <Link href={`/login?invite=${encodeURIComponent(token)}`}>У меня уже есть аккаунт</Link>
          </Button>
        </div>
      )}
    </>
  );
}

export default function JoinPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="flex h-16 items-center px-6">
        <Link href="/" aria-label="LeonIT — на главную">
          <Logo size={28} />
        </Link>
      </header>
      <main className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="w-full max-w-sm rounded-2xl border bg-card p-6 shadow-sm sm:p-8">
          <Suspense>
            <JoinContent />
          </Suspense>
        </div>
      </main>
    </div>
  );
}
