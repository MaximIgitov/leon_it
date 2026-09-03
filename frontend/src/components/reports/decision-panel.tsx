"use client";

import { useState } from "react";
import { Check, Loader2, Pause, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { DECISION_LABELS, type Decision } from "@/lib/api/reports";
import { cn } from "@/lib/utils";

export function DecisionPanel({
  decision,
  note,
  disabled,
  onDecide,
}: {
  decision: string | null;
  note: string | null;
  disabled?: boolean;
  onDecide: (decision: Decision, note: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState(note ?? "");
  const [pending, setPending] = useState<Decision | null>(null);

  const run = async (value: Decision) => {
    setPending(value);
    try {
      await onDecide(value, draft);
    } finally {
      setPending(null);
    }
  };

  const options: { value: Decision; icon: React.ElementType; variant: "default" | "destructive" | "outline" }[] = [
    { value: "advance", icon: Check, variant: "default" },
    { value: "hold", icon: Pause, variant: "outline" },
    { value: "reject", icon: X, variant: "destructive" },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Решение</CardTitle>
        <CardDescription>
          Решение принимает человек. Рекомендация модели — только подсказка.
          {decision ? (
            <span className="ml-1 font-medium text-foreground">
              Текущее: {DECISION_LABELS[decision as Decision] ?? decision}.
            </span>
          ) : null}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          rows={3}
          placeholder="Комментарий к решению (необязательно)"
          value={draft}
          disabled={disabled}
          onChange={(e) => setDraft(e.target.value)}
        />
        <div className="flex flex-wrap gap-2">
          {options.map((option) => (
            <Button
              key={option.value}
              variant={option.variant}
              disabled={disabled || pending !== null}
              onClick={() => run(option.value)}
              className={cn(decision === option.value && "ring-2 ring-ring ring-offset-2")}
            >
              {pending === option.value ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <option.icon className="mr-2 h-4 w-4" />
              )}
              {DECISION_LABELS[option.value]}
            </Button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
