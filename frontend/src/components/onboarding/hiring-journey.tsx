"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowRight, Briefcase, Check, Crown, Eye, FileCheck2, Flag, Layers, ListChecks, LockKeyhole, Map, MessageCircle, Play, Send, Sparkles, Target, Trophy, Users, X } from "lucide-react";
import Link, { usePathname, useRouter } from "@/lib/router";
import { useAuth } from "@/components/auth/auth-provider";
import { Mascot } from "@/components/brand/mascot";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { WORKSPACE_UPDATED_EVENT } from "@/lib/api/client";
import { dashboardApi } from "@/lib/api/dashboard";
import { vacanciesApi, type VacancyListItem } from "@/lib/api/vacancies";
import { toast } from "@/hooks/use-toast";

const STEPS = ([
  { id: "vacancy", title: "Первая вакансия", achievement: "Вакансия создана", text: "Добавьте вакансию и расскажите, кого ищете в команду.", action: "К вакансиям", target: "vacancies", icon: Briefcase },
  { id: "skills", title: "Нужные навыки", achievement: "Знаем, кого ищем", text: "Укажите навыки в описании вакансии.", action: "Открыть вакансию", target: "details", icon: Target },
  { id: "level", title: "Уровень опыта", achievement: "Ориентир задан", text: "Выберите уровень специалиста в вакансии.", action: "Открыть вакансию", target: "details", icon: Layers },
  { id: "questions", title: "Первые вопросы", achievement: "Есть что обсудить!", text: "Добавьте вопросы, которые помогут познакомиться с кандидатом.", action: "Добавить вопросы", target: "questions", icon: ListChecks },
  { id: "published", title: "Публикация", achievement: "Можно приглашать!", text: "Проверьте критерии и опубликуйте готовую вакансию.", action: "Открыть вакансию", target: "details", icon: Send },
  { id: "invited", title: "Первое приглашение", achievement: "Знакомство начинается", text: "Отправьте кандидату ссылку на интервью из карточки вакансии.", action: "Пригласить кандидата", target: "invite", icon: Users },
  { id: "opened", title: "Первый отклик", achievement: "Приглашение открыто", text: "Этап откроется, когда кандидат перейдёт по ссылке на интервью.", action: "К кандидатам", target: "candidates", icon: Eye },
  { id: "started", title: "Интервью началось", achievement: "Разговор пошёл!", text: "Первый кандидат приступил к вопросам — здесь появится награда.", action: "К кандидатам", target: "candidates", icon: Play },
  { id: "completed", title: "Первое интервью", achievement: "Первый разговор завершён", text: "Дождитесь первого завершённого интервью. Прогресс обновится автоматически.", action: "К кандидатам", target: "candidates", icon: MessageCircle },
  { id: "report", title: "Первый отчёт", achievement: "Ответы стали понятнее", text: "После интервью Леон подготовит разбор ответов по критериям вакансии.", action: "К кандидатам", target: "candidates", icon: FileCheck2 },
  { id: "decision", title: "Первое решение", achievement: "Решение принято!", text: "Посмотрите интервью и отметьте решение в отчёте кандидата.", action: "Посмотреть интервью", target: "candidates", icon: Flag },
  { id: "vacancies3", title: "Три вакансии", achievement: "Команда растёт", text: "Создайте три вакансии для своей команды.", action: "К вакансиям", target: "vacancies", icon: Briefcase },
  { id: "invited5", title: "Пять приглашений", achievement: "Круг знакомств шире", text: "Пригласите на интервью пять кандидатов.", action: "Пригласить кандидата", target: "invite", icon: Send },
  { id: "completed5", title: "Пять интервью", achievement: "Пять историй опыта", text: "Награда за пять завершённых интервью в вашей организации.", action: "К кандидатам", target: "candidates", icon: MessageCircle },
  { id: "reports5", title: "Пять отчётов", achievement: "Есть из кого выбирать", text: "Получите пять готовых отчётов по интервью.", action: "Посмотреть отчёты", target: "candidates", icon: FileCheck2 },
  { id: "decisions5", title: "Пять решений", achievement: "Пять шагов навстречу", text: "Отметьте решения по пяти интервью. Любое решение учитывается.", action: "К кандидатам", target: "candidates", icon: Flag },
  { id: "invited10", title: "Десять приглашений", achievement: "Новые знакомства", text: "Пригласите на интервью десять кандидатов.", action: "Пригласить кандидата", target: "invite", icon: Users },
  { id: "completed10", title: "Десять интервью", achievement: "Десять разговоров", text: "Десять завершённых интервью откроют эту награду.", action: "К кандидатам", target: "candidates", icon: MessageCircle },
  { id: "reports10", title: "Десять отчётов", achievement: "Опыт в деталях", text: "Леон подготовил десять отчётов — ещё одна награда на карте.", action: "Посмотреть отчёты", target: "candidates", icon: Sparkles },
  { id: "decisions10", title: "Десять решений", achievement: "Отличное начало!", text: "Примите решения по десяти интервью, чтобы завершить маршрут.", action: "К кандидатам", target: "candidates", icon: Trophy },
] as const).map((step, index) => {
  const x = [130, 255, 260, 150, 120, 245][index % 6];
  return { ...step, x, y: 100 + index * 140, side: x < 200 ? "right" : "left" };
});
const MAP_HEIGHT = STEPS[STEPS.length - 1].y + 100;
type StepId = typeof STEPS[number]["id"];
type SavedProgress = { completed: StepId[]; celebrated: StepId[]; notified: StepId[]; introduced: boolean; initialized: boolean; catalogVersion: number };
const emptyProgress = (): SavedProgress => ({ completed: [], celebrated: [], notified: [], introduced: false, initialized: false, catalogVersion: 2 });
const SEGMENTS = STEPS.map((step, index) => {
  const previous = STEPS[index - 1] ?? { x: step.x, y: 25 };
  const middle = (previous.y + step.y) / 2;
  return `M${previous.x} ${previous.y} C${previous.x} ${middle} ${step.x} ${middle} ${step.x} ${step.y}`;
});
const union = (a: StepId[], b: StepId[]) => STEPS.filter(step => a.includes(step.id) || b.includes(step.id)).map(step => step.id);

function readProgress(key: string): SavedProgress {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) ?? "null");
    const ids = (field: unknown): StepId[] => Array.isArray(field) ? STEPS.filter(step => field.includes(step.id)).map(step => step.id) : [];
    const completed = ids(value?.completed);
    return { completed, celebrated: ids(value?.celebrated).filter(id => completed.includes(id)), notified: ids(value?.notified).filter(id => completed.includes(id)), introduced: value?.introduced === true, initialized: value?.initialized === true || completed.length > 0, catalogVersion: value?.catalogVersion === 2 ? 2 : 1 };
  } catch { return emptyProgress(); }
}

type JourneyContextValue = { count: number | null; open: () => void };
const JourneyContext = createContext<JourneyContextValue | null>(null);

export function HiringJourneyTrigger({ compact = false, onOpen }: { compact?: boolean; onOpen?: () => void }) {
  const journey = useContext(JourneyContext);
  if (!journey) return null;
  return <button type="button" className="journey-trigger" data-compact={compact} onClick={() => { onOpen?.(); journey.open(); }} aria-label={`Карта достижений, пройдено ${journey.count ?? 0} из ${STEPS.length}`} title={compact ? "Достижения" : undefined}>
    <Map size={21} aria-hidden />{!compact && <span>Достижения</span>}<b>{journey.count ?? "…"}{!compact && <small>/{STEPS.length}</small>}</b>
  </button>;
}

function Achievement({ id, onClose, onOpen }: { id: StepId; onClose: () => void; onOpen: () => void }) {
  const [paused, setPaused] = useState(false);
  const step = STEPS.find(item => item.id === id)!;
  useEffect(() => {
    if (paused) return;
    const timer = window.setTimeout(onClose, 5500);
    return () => window.clearTimeout(timer);
  }, [onClose, paused]);
  return createPortal(<div className="journey-achievement" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} onFocus={() => setPaused(true)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setPaused(false); }}>
    <button className="journey-achievement-open" onClick={onOpen} aria-label={`${step.achievement}. Открыть карту`}><span className="journey-achievement-medal"><step.icon size={27} aria-hidden /></span><span><small>Достижение открыто</small><strong>{step.achievement}</strong></span></button>
    <button className="journey-achievement-close" onClick={onClose} aria-label="Закрыть достижение"><X size={17} /></button>
    <span className="sr-only" role="status">Достижение открыто: {step.achievement}</span>
  </div>, document.body);
}

export function HiringJourneyProvider({ children }: { children: ReactNode }) {
  const { me, can } = useAuth();
  const enabled = can("vacancy.write") && can("dashboard.read");
  const activityEnabled = can("dashboard.read");
  const pathname = usePathname();
  const router = useRouter();
  const storageKey = `leonit.journey.v1.live.${me?.organization.id}.${me?.id}`;
  const saved = useRef<SavedProgress>(emptyProgress());
  const request = useRef(0);
  const completedCount = useRef<number | null>(null);
  const mapViewport = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [completed, setCompleted] = useState<StepId[]>([]);
  const [displayed, setDisplayed] = useState<StepId[]>([]);
  const [vacancies, setVacancies] = useState<VacancyListItem[] | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [travel, setTravel] = useState<number | null>(null);
  const [celebration, setCelebration] = useState<number | null>(null);
  const [notifications, setNotifications] = useState<StepId[]>([]);
  const [reducedMotion, setReducedMotion] = useState(false);
  const ready = vacancies !== null;

  const remember = useCallback((patch: Partial<SavedProgress>) => {
    const stored = readProgress(storageKey);
    const next = { ...saved.current, ...patch };
    saved.current = { completed: union(stored.completed, next.completed), celebrated: union(stored.celebrated, next.celebrated), notified: union(stored.notified, next.notified), introduced: stored.introduced || next.introduced, initialized: stored.initialized || next.initialized, catalogVersion: next.catalogVersion };
    try { window.localStorage.setItem(storageKey, JSON.stringify(saved.current)); } catch { /* Progress remains available for this visit. */ }
  }, [storageKey]);

  const refresh = useCallback(async () => {
    if (!activityEnabled) return;
    const sequence = ++request.current;
    setLoading(true);
    try {
      const [list, overview] = await Promise.all([enabled ? vacanciesApi.list() : Promise.resolve([]), dashboardApi.overview("all")]);
      if (sequence !== request.current) return;
      // Save the last observed total per account; the first visit only establishes a baseline.
      let previous = completedCount.current;
      try {
        const stored = localStorage.getItem(`${storageKey}.completed-count`);
        if (stored !== null && stored.trim() !== "" && Number.isSafeInteger(Number(stored)) && Number(stored) >= 0) previous = Number(stored);
        localStorage.setItem(`${storageKey}.completed-count`, String(overview.completed));
      } catch { /* The in-memory baseline still prevents repeats during this visit. */ }
      completedCount.current = overview.completed;
      if (previous !== null && overview.completed > previous) {
        const count = overview.completed - previous;
        toast({ title: count === 1 ? "Новое интервью завершено" : "Завершены новые интервью", description: count === 1 ? "Ответы кандидата уже у команды." : `Интервью готовы к разбору: ${count}.`, celebrate: true, duration: 6000 });
      }
      if (!enabled) return;
      const published = list.some(vacancy => vacancy.published_at !== null || vacancy.status === "published");
      const flags: Record<StepId, boolean> = {
        vacancy: list.length > 0,
        skills: list.some(vacancy => vacancy.skills.length > 0),
        level: list.some(vacancy => vacancy.level !== null),
        questions: published || list.some(vacancy => vacancy.question_count > 0),
        published,
        invited: overview.invited > 0,
        opened: (overview.funnel.find(step => step.key === "opened")?.count ?? 0) > 0,
        started: (overview.funnel.find(step => step.key === "started")?.count ?? 0) > 0,
        completed: overview.completed > 0,
        report: overview.evaluated > 0,
        decision: overview.decided > 0,
        vacancies3: list.length >= 3,
        invited5: overview.invited >= 5,
        completed5: overview.completed >= 5,
        reports5: overview.evaluated >= 5,
        decisions5: overview.decided >= 5,
        invited10: overview.invited >= 10,
        completed10: overview.completed >= 10,
        reports10: overview.evaluated >= 10,
        decisions10: overview.decided >= 10,
      };
      const observed = STEPS.filter(step => flags[step.id]).map(step => step.id);
      const stored = readProgress(storageKey);
      const next = union(union(saved.current.completed, stored.completed), observed);
      const previousNotifications = union(saved.current.notified, stored.notified);
      // Existing teams get a map catch-up, without a stack of historical achievement toasts.
      const fresh = saved.current.initialized && saved.current.catalogVersion === 2 ? next.filter(id => !previousNotifications.includes(id)) : [];
      if (fresh.length) setNotifications(queue => union(queue, fresh));
      remember({ completed: next, notified: union(previousNotifications, next), initialized: true, catalogVersion: 2 });
      setCompleted(next); setVacancies(list); setError(false);
    } catch { if (sequence === request.current) setError(true); }
    finally { if (sequence === request.current) setLoading(false); }
  }, [enabled, activityEnabled, storageKey, remember]);

  useEffect(() => {
    if (!activityEnabled) return;
    saved.current = readProgress(storageKey);
    setCompleted(saved.current.completed); setDisplayed(saved.current.celebrated);
    setOpen(!saved.current.introduced);
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateMotion = () => setReducedMotion(media.matches);
    updateMotion(); media.addEventListener("change", updateMotion);
    const update = () => { if (document.visibilityState === "visible") void refresh(); };
    window.addEventListener(WORKSPACE_UPDATED_EVENT, update);
    window.addEventListener("focus", update);
    document.addEventListener("visibilitychange", update);
    const interval = window.setInterval(update, 30000);
    return () => {
      request.current++;
      window.clearInterval(interval); media.removeEventListener("change", updateMotion);
      window.removeEventListener(WORKSPACE_UPDATED_EVENT, update); window.removeEventListener("focus", update);
      document.removeEventListener("visibilitychange", update);
    };
  }, [activityEnabled, storageKey, refresh]);

  useEffect(() => { void refresh(); }, [pathname, refresh]);
  useEffect(() => { if (vacancies !== null && open && !saved.current.introduced) remember({ introduced: true }); }, [vacancies, open, remember]);

  const changeOpen = useCallback((next: boolean) => {
    setOpen(next); setTravel(null); setCelebration(null); setNotifications([]);
    if (next) { setDisplayed(saved.current.celebrated); void refresh(); }
    else remember({ introduced: true });
  }, [refresh, remember]);

  useEffect(() => {
    if (!open || !ready) return;
    const unseen = STEPS.findIndex(step => completed.includes(step.id) && !displayed.includes(step.id));
    const current = STEPS.findIndex(step => !completed.includes(step.id));
    const target = unseen >= 0 ? unseen : current >= 0 ? current : STEPS.length - 1;
    const frame = requestAnimationFrame(() => {
      const viewport = mapViewport.current;
      if (viewport) viewport.scrollTop = Math.max(0, STEPS[target].y - viewport.clientHeight * .42);
    });
    return () => cancelAnimationFrame(frame);
  }, [open, ready]);

  useEffect(() => {
    if (!open || vacancies === null) return;
    const nextIndex = STEPS.findIndex(step => completed.includes(step.id) && !displayed.includes(step.id));
    if (nextIndex < 0) return;
    if (reducedMotion) {
      setDisplayed(completed); remember({ celebrated: completed });
      return;
    }
    const start = window.setTimeout(() => {
      const viewport = mapViewport.current;
      viewport?.scrollTo({ top: Math.max(0, STEPS[nextIndex].y - viewport.clientHeight * .42), behavior: "smooth" });
      setTravel(nextIndex);
    }, 140);
    const finish = window.setTimeout(() => {
      const next = union(displayed, [STEPS[nextIndex].id]);
      setDisplayed(next); setCelebration(nextIndex); remember({ celebrated: next });
    }, 820);
    return () => { window.clearTimeout(start); window.clearTimeout(finish); };
  }, [open, vacancies, completed, displayed, reducedMotion, remember]);

  const closeAchievement = useCallback(() => setNotifications(queue => queue.slice(1)), []);
  const nextIndex = STEPS.findIndex(step => !completed.includes(step.id));
  const active = nextIndex < 0 ? null : STEPS[nextIndex];
  const draft = vacancies?.find(vacancy => vacancy.status === "draft") ?? vacancies?.[0];
  const publishedVacancy = vacancies?.find(vacancy => vacancy.status === "published");
  const href = (index: number) => {
    const target = STEPS[index].target;
    if (target === "candidates") return "/candidates";
    if (target === "invite" && publishedVacancy) return `/vacancies/${publishedVacancy.id}?tab=candidates`;
    if (target === "questions" && draft) return `/vacancies/${draft.id}?tab=questions`;
    if (target === "details" && draft) return `/vacancies/${draft.id}`;
    return "/vacancies";
  };

  return <JourneyContext.Provider value={enabled ? { count: vacancies === null ? null : completed.length, open: () => changeOpen(true) } : null}>
    {children}
    {enabled && <Dialog open={open} onOpenChange={changeOpen}>
      <DialogContent className="journey-modal flex flex-col gap-0 overflow-hidden p-0 sm:max-w-[720px]">
        <DialogHeader className="journey-heading"><div><DialogTitle>Ваш путь с Леоном</DialogTitle><p className="journey-subtitle">Знакомьтесь, выбирайте, собирайте награды</p></div><div className="journey-progress"><Trophy size={24} aria-hidden /><strong>{displayed.length}<span> / {STEPS.length}</span></strong></div></DialogHeader>
        {vacancies === null ? <div className="journey-loading">{error ? <><p role="alert">Не удалось загрузить прогресс.</p><Button variant="outline" onClick={() => void refresh()} disabled={loading}>Попробовать снова</Button></> : <><Skeleton className="h-24 rounded-2xl" /><Skeleton className="h-72 rounded-3xl" /></>}</div> : <div className="journey-body" ref={mapViewport}>
          <div className="journey-map" style={{ height: MAP_HEIGHT }} aria-label="Карта этапов">
            {Array.from({ length: Math.ceil(MAP_HEIGHT / 960) }, (_, index) => <div key={index} className="journey-scenery" style={{ top: index * 960 }} aria-hidden />)}
            <Mascot name="fox" className="journey-map-fox" eager />
            <svg className="journey-path" viewBox={`0 0 400 ${MAP_HEIGHT}`} preserveAspectRatio="none" aria-hidden>
              <path d={SEGMENTS.join(" ")} className="journey-path-track" />
              {travel !== null && !reducedMotion && <g key={travel} className="journey-traveler"><circle r={12} fill="#ffda42" stroke="white" strokeWidth={4} /><animateMotion path={SEGMENTS[travel]} dur="0.65s" fill="freeze" /></g>}
            </svg>
            <ol>{STEPS.map((step, index) => {
              const done = displayed.includes(step.id);
              const available = completed.includes(step.id) || index === nextIndex;
              return <li key={step.id} className="journey-stop" style={{ left: `${step.x / 4}%`, top: step.y }} data-side={step.side} data-complete={done} data-current={index === nextIndex}>
                <button className="journey-node" disabled={!available} aria-label={`${step.title}: ${done ? "пройдено" : index === nextIndex ? "следующий этап" : "впереди"}`} aria-current={index === nextIndex ? "step" : undefined} onClick={() => { changeOpen(false); router.push(href(index)); }}>
                  {done ? <Check size={31} strokeWidth={3.5} /> : available ? <step.icon size={29} strokeWidth={2.5} /> : <LockKeyhole size={23} />}
                </button>
                <span className="journey-crown" aria-hidden><Crown size={30} strokeWidth={2.5} fill="currentColor" /></span>
                <div className="journey-stop-label"><strong>{step.title}</strong><span>{done ? "Готово!" : index === nextIndex ? "Начните здесь" : `Этап ${index + 1}`}</span></div>
                {celebration === index && !reducedMotion && <div className="journey-confetti" key={index} aria-hidden>{Array.from({ length: 18 }, (_, particle) => <i key={particle} style={{ "--x": `${Math.cos(particle * 2.4) * (65 + particle * 3)}px`, "--y": `${Math.sin(particle * 2.4) * 90 + 50}px`, "--turn": `${particle * 47}deg`, "--color": ["#84d63b", "#ffda42", "#24acf2", "#ffae36"][particle % 4] } as CSSProperties} />)}</div>}
              </li>;
            })}</ol>
          </div>
          <span className="sr-only" role="status">Пройдено {displayed.length} из {STEPS.length} этапов.</span>
        </div>}
        {vacancies !== null && <div className="journey-intro"><div><h2>{active ? active.title : "Все награды собраны!"}</h2><p>{active ? active.text : "Все 20 достижений открыты. Продолжайте знакомиться с кандидатами."}</p>{error && <button className="journey-refresh" onClick={() => void refresh()} disabled={loading}>Прогресс не обновлён. Повторить</button>}</div><Button asChild><Link href={active ? href(nextIndex) : "/dashboard"} onClick={() => changeOpen(false)}>{active ? active.action : "К обзору"}<ArrowRight size={17} /></Link></Button></div>}
      </DialogContent>
    </Dialog>}
    {enabled && !open && notifications[0] && <Achievement key={notifications[0]} id={notifications[0]} onClose={closeAchievement} onOpen={() => changeOpen(true)} />}
  </JourneyContext.Provider>;
}
