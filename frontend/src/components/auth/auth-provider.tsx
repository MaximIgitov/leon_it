"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { Logo } from "@/components/brand/logo";
import { accountsApi, type Me } from "@/lib/api/accounts";
import { ApiError, getAccessToken, setAccessToken } from "@/lib/api/client";

type AuthState = {
  me: Me | null;
  loading: boolean;
  refresh: () => Promise<Me | null>;
  signIn: (token: string) => Promise<Me | null>;
  signOut: () => void;
  can: (permission: string) => boolean;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getAccessToken()) {
      setMe(null);
      setLoading(false);
      return null;
    }
    try {
      const next = await accountsApi.me();
      setMe(next);
      return next;
    } catch (error) {
      // 401/403 — сессия отозвана или права изменились: токен больше не нужен.
      // Сетевая ошибка — в том числе запрос, прерванный уходом со страницы, —
      // не разлогинивает: иначе RequireAuth уводит на /login посреди навигации
      // (воспроизводилось в WebKit), а /login тут же возвращает на дашборд.
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
        setAccessToken(null);
        setMe(null);
      }
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(
    async (token: string) => {
      setAccessToken(token);
      setLoading(true);
      return refresh();
    },
    [refresh],
  );

  const signOut = useCallback(() => {
    setAccessToken(null);
    setMe(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      me,
      loading,
      refresh,
      signIn,
      signOut,
      can: (permission) => Boolean(me?.permissions.includes(permission)),
    }),
    [me, loading, refresh, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth должен использоваться внутри AuthProvider");
  return context;
}

export function AuthLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="animate-pulse">
        <Logo size={36} />
      </div>
    </div>
  );
}

/** Оболочка защищённых маршрутов: без сессии отправляет на /login с возвратом. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { me, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !me) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, me, router, pathname]);

  if (loading || !me) return <AuthLoading />;
  return <>{children}</>;
}
