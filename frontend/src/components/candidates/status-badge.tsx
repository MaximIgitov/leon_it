import { Badge } from "@/components/ui/badge";
import { INTERVIEW_STATUS_LABELS, type InterviewStatus } from "@/lib/api/candidates";

const VARIANTS: Partial<Record<InterviewStatus, "default" | "secondary" | "destructive" | "outline">> = {
  evaluated: "default",
  advanced: "default",
  rejected: "destructive",
  expired: "outline",
  cancelled: "outline",
};

export function InterviewStatusBadge({ status }: { status: InterviewStatus }) {
  return <Badge variant={VARIANTS[status] ?? "secondary"}>{INTERVIEW_STATUS_LABELS[status]}</Badge>;
}
