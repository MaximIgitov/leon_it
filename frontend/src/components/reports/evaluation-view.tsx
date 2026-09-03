"use client";

import { AlertTriangle, CheckCircle2, HelpCircle, Quote, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RECOMMENDATION_LABELS, type EvaluationOutput, type Evidence, type Recommendation } from "@/lib/api/reports";
import { cn } from "@/lib/utils";

export function RecommendationBadge({ value, score }: { value: Recommendation | null; score: number | null }) {
  if (!value) return <Badge variant="secondary">Оценка готовится</Badge>;
  const icon =
    value === "fit" ? <CheckCircle2 className="mr-1 h-3.5 w-3.5" /> : value === "no_fit" ? <XCircle className="mr-1 h-3.5 w-3.5" /> : <HelpCircle className="mr-1 h-3.5 w-3.5" />;
  const variant = value === "fit" ? "default" : value === "no_fit" ? "destructive" : "secondary";
  return (
    <Badge variant={variant} className="gap-0">
      {icon}
      {RECOMMENDATION_LABELS[value]}
      {score !== null ? <span className="ml-1.5 opacity-80">{Math.round(score)}</span> : null}
    </Badge>
  );
}

function EvidenceList({
  items,
  onSeek,
}: {
  items: Evidence[];
  onSeek?: (answerId: string, seconds: number | null) => void;
}) {
  if (!items?.length) return null;
  return (
    <ul className="mt-2 space-y-1">
      {items.map((item, index) => (
        <li key={`${item.answer_id}-${index}`}>
          <button
            type="button"
            onClick={() => onSeek?.(item.answer_id, item.start_s)}
            className="flex w-full items-start gap-2 rounded-md p-1.5 text-left text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            title="Перейти к этому месту в видео"
          >
            <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              «{item.quote}»
              <span className="ml-1 text-xs opacity-70">
                вопр. {item.question_index + 1}
                {item.start_s !== null ? ` · ${Math.floor(item.start_s / 60)}:${String(Math.floor(item.start_s % 60)).padStart(2, "0")}` : ""}
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function ScoreDots({ score }: { score: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`Балл ${score} из 4`}>
      {[1, 2, 3, 4].map((n) => (
        <span key={n} className={cn("h-2.5 w-2.5 rounded-full", n <= score ? "bg-primary" : "bg-muted")} />
      ))}
    </span>
  );
}

export function EvaluationView({
  output,
  onSeek,
}: {
  output: EvaluationOutput;
  onSeek?: (answerId: string, seconds: number | null) => void;
}) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Заключение</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="leading-relaxed">{output.summary}</p>
          {output.transcript_quality_note ? (
            <p className="flex items-start gap-2 text-muted-foreground">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {output.transcript_quality_note}
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">Уверенность модели: {Math.round(output.confidence * 100)}%</p>
        </CardContent>
      </Card>

      {output.competency_scores?.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Компетенции</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {output.competency_scores.map((item) => (
              <div key={item.competency_id}>
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{item.name}</span>
                  <span className="flex items-center gap-2 text-sm">
                    <ScoreDots score={item.score} /> {item.score}/4
                  </span>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{item.rationale}</p>
                <EvidenceList items={item.evidence} onSeek={onSeek} />
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Сильные стороны</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {output.strengths.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Зоны роста</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {output.growth_areas.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Риски</CardTitle>
          </CardHeader>
          <CardContent>
            {output.risks.length ? (
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {output.risks.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Не выявлены.</p>
            )}
            {output.red_flags?.length ? (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-destructive">
                {output.red_flags.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Что проверить на живом созвоне</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1 pl-5 text-sm">
              {output.follow_up_checks.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      {output.skills?.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Навыки</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {output.skills.map((skill) => (
              <Badge key={skill.name} variant="outline" className="font-normal">
                {skill.name} · {skill.level}
              </Badge>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {output.question_assessments?.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">По вопросам</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {output.question_assessments.map((item) => (
              <div key={item.question_index}>
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">Вопрос {item.question_index + 1}</span>
                  <span className="flex items-center gap-2 text-sm">
                    <ScoreDots score={item.score} /> {item.score}/4
                  </span>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{item.comment}</p>
                {item.covered_points.length || item.missed_points.length ? (
                  <div className="mt-2 grid gap-2 sm:grid-cols-2 text-xs">
                    <div>
                      <p className="font-medium text-success">Раскрыто</p>
                      <ul className="list-disc pl-4">
                        {item.covered_points.map((p) => (
                          <li key={p}>{p}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <p className="font-medium text-warning">Не раскрыто</p>
                      <ul className="list-disc pl-4">
                        {item.missed_points.map((p) => (
                          <li key={p}>{p}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                ) : null}
                <EvidenceList items={item.evidence} onSeek={onSeek} />
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
