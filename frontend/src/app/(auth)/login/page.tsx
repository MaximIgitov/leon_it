import { Suspense } from "react";

import { LoginForm } from "@/components/auth/auth-form";

export const metadata = { title: "Вход" };

export default function LoginPage() {
  return (
    <>
      <h1 className="mb-6 text-2xl font-bold tracking-tight">С возвращением!</h1>
      <Suspense>
        <LoginForm />
      </Suspense>
    </>
  );
}
