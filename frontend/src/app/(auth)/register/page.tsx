import { Suspense } from "react";

import { RegisterForm } from "@/components/auth/auth-form";

export const metadata = { title: "Регистрация" };

export default function RegisterPage() {
  return (
    <>
      <h1 className="mb-1 text-2xl font-bold tracking-tight">Регистрация</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Для рекрутеров и нанимающих менеджеров. Кандидатам аккаунт не нужен — они
        проходят интервью по ссылке.
      </p>
      <Suspense>
        <RegisterForm />
      </Suspense>
    </>
  );
}
