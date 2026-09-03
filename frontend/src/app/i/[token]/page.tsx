"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { CalendarClock, Camera, Clock3, ListChecks, Loader2, Mic } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { publicApi, type InvitationPublic } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";

function minutesLabel(minutes: number): string {
  const mod10 = minutes % 10;
  const mod100 = minutes % 100;
  if (mod10 === 1 && mod100 !== 11) return `${minutes} минута`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return `${minutes} минуты`;
  return `${minutes} минут`;
}

function Unavailable({ title, text }: { title: string; text: string }) {
  return (
    <div className="text-center">
      <h1 className="text-xl font-bold">{title}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{text}</p>
    </div>
  );
}

function ConsentForm({
  token,
  invitation,
  onDone,
}: {
  token: string;
  invitation: InvitationPublic;
  onDone: (next: InvitationPublic) => void;
}) {
  const [fullName, setFullName] = useState(invitation.candidate_full_name);
  const [email, setEmail] = useState(invitation.candidate_email);
  const [personalData, setPersonalData] = useState(false);
  const [privacy, setPrivacy] = useState(false);
  const [newsletter, setNewsletter] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const docs = Object.fromEntries(invitation.consent_documents.map((d) => [d.slug, d]));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const next = await publicApi.consent(token, {
        full_name: fullName,
        email,
        personal_data_accepted: personalData,
        privacy_policy_accepted: privacy,
        newsletter_accepted: newsletter,
        document_versions: Object.fromEntries(
          invitation.consent_documents.map((d) => [d.slug, d.version]),
        ),
      });
      onDone(next);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось сохранить согласие");
    } finally {
      setPending(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="full_name">Имя и фамилия</Label>
          <Input id="full_name" required autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="email">E-mail</Label>
          <Input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
      </div>
      <div className="space-y-3 rounded-lg border p-4">
        <label className="flex items-start gap-3 text-sm">
          <Checkbox checked={personalData} onCheckedChange={(v) => setPersonalData(v === true)} className="mt-0.5" />
          <span>
            {docs["personal-data-consent"]?.checkbox_label ??
              "Я даю согласие на обработку моих персональных данных, включая видеозапись и голос"}{" "}
            —{" "}
            <Link href="/legal/personal-data-consent" target="_blank" className="text-primary underline-offset-4 hover:underline">
              текст согласия
            </Link>
            <span className="text-destructive"> *</span>
          </span>
        </label>
        <label className="flex items-start gap-3 text-sm">
          <Checkbox checked={privacy} onCheckedChange={(v) => setPrivacy(v === true)} className="mt-0.5" />
          <span>
            Я ознакомился(ась) с{" "}
            <Link href="/legal/privacy-policy" target="_blank" className="text-primary underline-offset-4 hover:underline">
              политикой конфиденциальности
            </Link>
            <span className="text-destructive"> *</span>
          </span>
        </label>
        <label className="flex items-start gap-3 text-sm">
          <Checkbox checked={newsletter} onCheckedChange={(v) => setNewsletter(v === true)} className="mt-0.5" />
          <span>
            {docs["newsletter-consent"]?.checkbox_label ?? "Хочу получать рассылку о вакансиях и новостях"}{" "}
            —{" "}
            <Link href="/legal/newsletter-consent" target="_blank" className="text-primary underline-offset-4 hover:underline">
              условия
            </Link>{" "}
            <span className="text-muted-foreground">(необязательно)</span>
          </span>
        </label>
      </div>
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      <Button type="submit" size="lg" className="w-full" disabled={pending || !personalData || !privacy || !fullName.trim() || !email.trim()}>
        {pending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        Продолжить
      </Button>
      <p className="text-center text-xs text-muted-foreground">
        Решение по итогам интервью принимает сотрудник компании, а не алгоритм.
      </p>
    </form>
  );
}

export default function InvitationPage() {
  const params = useParams<{ token: string }>();
  const [invitation, setInvitation] = useState<InvitationPublic | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    publicApi
      .invitation(params.token)
      .then(setInvitation)
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : "Ссылка недоступна"));
  }, [params.token]);

  let content: React.ReactNode;
  if (error) {
    content = <Unavailable title="Ссылка недействительна" text={error} />;
  } else if (!invitation) {
    content = <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />;
  } else if (invitation.status === "expired") {
    content = (
      <Unavailable
        title="Срок ссылки истёк"
        text="Попросите рекрутера прислать новую ссылку — приглашение можно продлить."
      />
    );
  } else if (invitation.status === "cancelled") {
    content = <Unavailable title="Приглашение отменено" text="Если это ошибка, свяжитесь с рекрутером." />;
  } else if (!["invited", "opened", "consented", "in_progress"].includes(invitation.status)) {
    content = (
      <Unavailable
        title="Интервью уже завершено"
        text="Спасибо! Ответы переданы рекрутеру. Результат сообщат по e-mail."
      />
    );
  } else {
    content = (
      <>
        <p className="text-sm text-muted-foreground">{invitation.organization_name}</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight sm:text-3xl">
          Видеоинтервью: {invitation.vacancy_title}
        </h1>
        {invitation.intro_text ? (
          <p className="mt-3 whitespace-pre-wrap text-muted-foreground">{invitation.intro_text}</p>
        ) : null}
        <dl className="mt-6 grid gap-3 sm:grid-cols-2">
          {[
            [ListChecks, `${invitation.question_count} вопр. · около ${minutesLabel(invitation.estimated_minutes)}`],
            [Clock3, `Подготовка ${invitation.prep_seconds} с · ответ до ${Math.round(invitation.max_answer_seconds / 60)} мин`],
            [Camera, "Нужны камера, микрофон и тихое место"],
            [CalendarClock, `Пройти до ${new Date(invitation.expires_at).toLocaleDateString("ru-RU")}`],
          ].map(([Icon, text]) => {
            const IconComponent = Icon as React.ElementType;
            return (
              <div key={String(text)} className="flex items-center gap-3 rounded-lg border p-3 text-sm">
                <IconComponent className="h-4 w-4 shrink-0 text-primary" />
                <span>{String(text)}</span>
              </div>
            );
          })}
        </dl>
        <p className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <Mic className="h-4 w-4" />
          Можно прерваться и вернуться по этой же ссылке — продолжите с первого неотвеченного вопроса.
        </p>
        <div className="mt-8">
          {invitation.needs_consent ? (
            <ConsentForm token={params.token} invitation={invitation} onDone={setInvitation} />
          ) : (
            <div className="rounded-lg border bg-muted/40 p-4 text-sm">
              Согласие получено. Проверка камеры и микрофона и комната интервью подключаются
              следующим шагом разработки.
            </div>
          )}
        </div>
      </>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="flex h-16 items-center px-6">
        <Logo size={28} />
      </header>
      <main className="flex flex-1 justify-center px-4 pb-16">
        <div className="w-full max-w-2xl rounded-2xl border bg-card p-6 shadow-sm sm:p-8">{content}</div>
      </main>
    </div>
  );
}
