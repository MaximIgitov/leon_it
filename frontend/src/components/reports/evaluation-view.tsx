"use client";

import { AlertTriangle, ArrowUpRight, CheckCircle2, ChevronDown, HelpCircle, Quote, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { RECOMMENDATION_LABELS, type EvaluationOutput, type Evidence, type Recommendation } from "@/lib/api/reports";

export function RecommendationBadge({ value, score }: { value: Recommendation | null; score: number | null }) {
  if (!value) return <Badge variant="secondary">Оценка готовится</Badge>;
  const Icon = value === "fit" ? CheckCircle2 : value === "no_fit" ? XCircle : HelpCircle;
  return <Badge variant={value === "fit" ? "default" : value === "no_fit" ? "destructive" : "secondary"} className="gap-1"><Icon size={15} />{RECOMMENDATION_LABELS[value]}{score !== null && <span className="ml-1">{Math.round(score)}</span>}</Badge>;
}

function EvidenceList({ items, onSeek }: { items: Evidence[]; onSeek?: (answerId: string, seconds: number | null) => void }) {
  if (!items?.length) return null;
  return <ul className="report-evidence">{items.map((item, index) => <li key={`${item.answer_id}-${index}`}>
    <button type="button" disabled={!onSeek} onClick={() => onSeek?.(item.answer_id, item.start_s)} className="evidence-quote" title={item.verified === false ? "Цитата не подтверждена — проверьте запись" : "Открыть ответ"}>
      {item.verified === false ? <AlertTriangle size={18} className="text-warning" aria-label="Не подтверждено" /> : <Quote size={18} aria-hidden />}
      <span><q>{item.quote}</q><small>Вопрос {item.question_index + 1}{item.start_s !== null ? ` · ${Math.floor(item.start_s / 60)}:${String(Math.floor(item.start_s % 60)).padStart(2, "0")}` : ""}{item.verified === false ? " · требует проверки" : ""}</small></span>{onSeek && <ArrowUpRight size={17} aria-hidden />}
    </button>
  </li>)}</ul>;
}

function Score({ score }: { score: number }) {
  return <span className="report-competency-score"><span className="score-segments" aria-hidden>{[1, 2, 3, 4].map(n => <i key={n} data-filled={n <= score} />)}</span><strong>{score}<span>/4</span></strong></span>;
}

export function quoteStats(output: EvaluationOutput): { found: number; total: number } {
  const all: Evidence[] = [...(output.competency_scores ?? []).flatMap(item => item.evidence ?? []), ...(output.question_assessments ?? []).flatMap(item => item.evidence ?? []), ...(output.skills ?? []).flatMap(item => item.evidence ?? [])];
  return { total: all.length, found: all.filter(item => item.verified !== false).length };
}

export function EvaluationView({ output, onSeek }: { output: EvaluationOutput; onSeek?: (answerId: string, seconds: number | null) => void }) {
  const quotes = quoteStats(output);
  return <div className="evaluation-view">
    <section className="report-card evaluation-summary"><h2>Общее впечатление</h2><p className="evaluation-summary-text">{output.summary}</p>
      <div className="evaluation-confidence"><span>Уверенность ИИ <strong>{Math.round(output.confidence * 100)}%</strong></span>{quotes.total > 0 && <span>Подтверждено цитат <strong>{quotes.found} из {quotes.total}</strong></span>}</div>
      {output.transcript_quality_note && <p className="report-notice"><AlertTriangle size={18} />{output.transcript_quality_note}</p>}
      {quotes.found < quotes.total && <p className="report-notice">Цитаты без подтверждения помечены ниже. Проверьте их по записи.</p>}
    </section>
    {output.competency_scores?.length > 0 && <section className="report-card evaluation-competencies"><h2>Оценка по критериям</h2><div className="competency-list">{output.competency_scores.map(item => <article key={item.competency_id} className="competency-row"><header><h3>{item.name}</h3><Score score={item.score} /></header><p>{item.rationale}</p><EvidenceList items={item.evidence} onSeek={onSeek} /></article>)}</div></section>}
    <section className="report-card evaluation-strengths"><h2>Сильные стороны</h2><ul className="report-checklist">{output.strengths.map(item => <li key={item}><CheckCircle2 size={18} aria-hidden /><span>{item}</span></li>)}</ul>{!output.strengths.length && <p className="report-muted">В отчёте пока нет наблюдений.</p>}</section>
    <section className="report-card"><h2>Что обсудить подробнее</h2><ul className="report-bullets">{output.growth_areas.map(item => <li key={item}>{item}</li>)}</ul>{output.follow_up_checks.length > 0 && <div className="report-followups"><h3>На следующей встрече</h3><ul className="report-bullets">{output.follow_up_checks.map(item => <li key={item}>{item}</li>)}</ul></div>}{!output.growth_areas.length && !output.follow_up_checks.length && <p className="report-muted">Дополнительных вопросов пока нет.</p>}</section>
    <section className="report-card"><h2>Риски</h2>{output.risks.length ? <ul className="report-bullets">{output.risks.map(item => <li key={item}>{item}</li>)}</ul> : <p className="report-muted">По ответам не выявлены.</p>}{output.red_flags?.length > 0 && <ul className="report-bullets text-destructive">{output.red_flags.map(item => <li key={item}>{item}</li>)}</ul>}</section>
    {output.skills?.length > 0 && <section className="report-card"><h2>Навыки</h2><ul className="report-skills">{output.skills.map(skill => <li key={skill.name}><div><strong>{skill.name}</strong><span>{skill.level}</span></div><EvidenceList items={skill.evidence} onSeek={onSeek} /></li>)}</ul></section>}
    {output.question_assessments?.length > 0 && <section className="report-card evaluation-questions"><h2>Разбор вопросов</h2>{output.question_assessments.map(item => <details key={item.question_index} className="assessment-question"><summary><span>Вопрос {item.question_index + 1}</span><Score score={item.score} /><ChevronDown size={18} /></summary><div className="assessment-body"><p>{item.comment}</p><div className="assessment-points">{item.covered_points.length > 0 && <div><h3>Раскрыто</h3><ul className="report-bullets">{item.covered_points.map(point => <li key={point}>{point}</li>)}</ul></div>}{item.missed_points.length > 0 && <div><h3>Стоит уточнить</h3><ul className="report-bullets">{item.missed_points.map(point => <li key={point}>{point}</li>)}</ul></div>}</div><EvidenceList items={item.evidence} onSeek={onSeek} />{onSeek && item.answer_id && <button className="report-text-link" onClick={() => onSeek(item.answer_id!, 0)}>Открыть ответ<ArrowUpRight size={17} /></button>}</div></details>)}</section>}
  </div>;
}
