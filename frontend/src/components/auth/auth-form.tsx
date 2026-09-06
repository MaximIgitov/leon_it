"use client";

import { Skeleton } from "@/components/ui/skeleton";

import Link from "@/lib/router";
import { useRouter, useSearchParams } from "@/lib/router";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { accountsApi, type InvitePreview } from "@/lib/api/accounts";
import { ApiError } from "@/lib/api/client";
import { roleLabel } from "@/lib/roles";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Что-то пошло не так. Попробуйте ещё раз.";
}

function safeNext(value: string | null): string {
  // Возвращаемся только на свои страницы: внешний адрес в next — открытый редирект.
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/dashboard";
}

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { signIn } = useAuth();
  const inviteToken = params.get("invite");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const { access_token } = await accountsApi.login({ email, password });
      await signIn(access_token);
      if (inviteToken) {
        await accountsApi.acceptInvite(inviteToken);
        await signIn(access_token);
      }
      router.replace(safeNext(params.get("next")));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="email">E-mail</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">Пароль</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      <Button type="submit" className="w-full" disabled={pending}>
        {pending ? <Skeleton className="mr-2 h-4 w-4 rounded-md" /> : null}
        Войти
      </Button>
      <p className="text-center text-sm text-muted-foreground">
        Нет аккаунта?{" "}
        <Link
          href={inviteToken ? `/register?invite=${encodeURIComponent(inviteToken)}` : "/register"}
          className="text-primary underline-offset-4 hover:underline"
        >
          Зарегистрироваться
        </Link>
      </p>
    </form>
  );
}

export function RegisterForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { signIn } = useAuth();
  const inviteToken = params.get("invite");
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!inviteToken) return;
    accountsApi
      .previewInvite(inviteToken)
      .then((next) => {
        setPreview(next);
        if (next.email) setEmail(next.email);
      })
      .catch((caught) => setError(errorMessage(caught)));
  }, [inviteToken]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const { access_token } = await accountsApi.register({
        email,
        password,
        full_name: fullName,
        organization_name: inviteToken ? undefined : organizationName || undefined,
        invite_token: inviteToken ?? undefined,
      });
      await signIn(access_token);
      router.replace("/dashboard");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      {preview ? (
        <div className="rounded-lg border bg-secondary/50 p-3 text-sm">
          {preview.valid ? (
            <>
              Вы присоединяетесь к <span className="font-medium">{preview.organization_name}</span>{" "}
              с ролью <span className="font-medium">{roleLabel(preview.role)}</span>.
            </>
          ) : (
            <span className="text-destructive">{preview.reason}</span>
          )}
        </div>
      ) : null}
      <div className="space-y-2">
        <Label htmlFor="full_name">Имя и фамилия</Label>
        <Input
          id="full_name"
          autoComplete="name"
          required
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="email">Рабочий e-mail</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          readOnly={Boolean(preview?.email)}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">Пароль</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <p className="text-xs text-muted-foreground">Не короче 8 символов.</p>
      </div>
      {!inviteToken ? (
        <div className="space-y-2">
          <Label htmlFor="organization">Компания</Label>
          <Input
            id="organization"
            autoComplete="organization"
            placeholder="Название организации"
            value={organizationName}
            onChange={(event) => setOrganizationName(event.target.value)}
          />
        </div>
      ) : null}
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      <Button type="submit" className="w-full" disabled={pending || preview?.valid === false}>
        {pending ? <Skeleton className="mr-2 h-4 w-4 rounded-md" /> : null}
        {inviteToken ? "Присоединиться" : "Создать аккаунт"}
      </Button>
      <p className="text-center text-sm text-muted-foreground">
        Уже есть аккаунт?{" "}
        <Link
          href={inviteToken ? `/login?invite=${encodeURIComponent(inviteToken)}` : "/login"}
          className="text-primary underline-offset-4 hover:underline"
        >
          Войти
        </Link>
      </p>
    </form>
  );
}
