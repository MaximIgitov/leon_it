"use client";

import { ArrowRight, Briefcase, Crosshair, Medal, Quotes, SealCheck, Smiley, SmileyMeh, SmileySad, TrendUp } from "@phosphor-icons/react";
import Link from "@/lib/router";
import { Mascot } from "@/components/brand/mascot";
import type { DashboardOverview } from "@/lib/api/dashboard";
import { formatCount, formatPercent, formatScore, plural } from "./format";

export const TILE_GRID = "metric-grid";
export const TILE_COUNT = 6;

export function tiles(data: DashboardOverview) {
  return [
    { label: "Приглашено", value: formatCount(data.invited), hint: "", icon: Crosshair },
    { label: "Завершили интервью", value: formatCount(data.completed), hint: `Из ${formatCount(data.invited)} приглашённых`, icon: Briefcase },
    { label: "Конверсия", value: formatPercent(data.completion_rate), hint: "Из приглашения в интервью", icon: TrendUp },
    { label: "Средний балл", value: formatScore(data.avg_fit_score), hint: `${formatCount(data.evaluated)} ${plural(data.evaluated, ["интервью оценено", "интервью оценены", "интервью оценены"])}`, icon: Medal },
    { label: "Согласие с ИИ", value: formatPercent(data.ai_agreement), hint: `На основе ${data.ai_agreement_pairs} ${plural(data.ai_agreement_pairs, ["решения", "решений", "решений"])}`, icon: SealCheck },
    { label: "Точность цитат", value: formatPercent(data.quote_verification_rate), hint: "Подтверждены ответами кандидатов", icon: Quotes },
  ];
}

export function MetricTiles({ data }: { data: DashboardOverview }) {
  const recommendations = [
    { icon: Smiley, label: "Подходит", value: data.recommendation_breakdown.fit, tone: "fit" },
    { icon: SmileySad, label: "Не подходит", value: data.recommendation_breakdown.no_fit, tone: "no-fit" },
    { icon: SmileyMeh, label: "Нужна проверка", value: data.recommendation_breakdown.needs_check, tone: "check" },
  ];
  return <div className="dashboard-grid">
    <section className="overview-card overview-primary">
      <Crosshair className="overview-icon" size={28} weight="regular" aria-hidden />
      <h2>Приглашено</h2>
      <strong className="overview-value overview-lead-value">{formatCount(data.invited)}</strong>
      <div className="overview-qualification">
        <h3>Рекомендации ИИ</h3>
        <div className="qualification-counts">{recommendations.map(({ icon: Icon, ...item }) => <div key={item.tone} className={`qualification-${item.tone}`} title={`${item.label}: ${item.value}`} aria-label={`${item.label}: ${item.value}`}><Icon size={23} aria-hidden /><strong>{formatCount(item.value)}</strong></div>)}</div>
        <p className="qualification-description">ИИ оценивает ответы по критериям вакансии. Здесь показано число кандидатов по каждой рекомендации.</p>
      </div>
    </section>
    <section className="overview-banner">
      <div className="overview-banner-copy"><div><h2>{data.awaiting_decision ? "Ждут вашего решения" : "Можно начинать"}</h2><p>{data.awaiting_decision ? `${data.awaiting_decision} ${plural(data.awaiting_decision, ["кандидат", "кандидата", "кандидатов"])}` : "Пригласите первых кандидатов"}</p></div>
      <Link href={data.awaiting_decision ? (data.vacancy ? `/vacancies/${data.vacancy.id}?tab=candidates` : "/candidates") : "/vacancies"}>{data.awaiting_decision ? "К кандидатам" : "К вакансиям"}<ArrowRight size={19} aria-hidden /></Link></div>
      <div className="overview-banner-art" aria-hidden><span className="banner-gold-glow" /><span className="banner-spark banner-spark-one">✦</span><span className="banner-spark banner-spark-two">✧</span><Mascot name="fox" eager /></div>
    </section>
    {tiles(data).slice(1).map(({ icon: Icon, ...tile }) => <section key={tile.label} className="overview-card">
      <Icon className="overview-icon" size={28} weight="regular" aria-hidden />
      <h2>{tile.label}</h2><strong className="overview-value">{tile.value}</strong><p>{tile.hint}</p>
    </section>)}
  </div>;
}
