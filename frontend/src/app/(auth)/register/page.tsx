import { Suspense } from "react";

import { RegisterForm } from "@/components/auth/auth-form";

export const metadata = { title: "Регистрация" };

export default function RegisterPage() {
  return (
    <>
      <h1 className="mb-1 text-2xl font-bold tracking-tight">Создать аккаунт</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Создайте пространство для вашей команды.
      </p>
      <Suspense>
        <RegisterForm />
      </Suspense>
    </>
  );
}
