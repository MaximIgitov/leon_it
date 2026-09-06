"use client";

import { RowsSkeleton } from "@/components/ui/skeleton";

import Link from "@/lib/router";
import { useCallback, useEffect, useState } from "react";
import { Search } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { InviteDialog } from "@/components/candidates/invite-dialog";
import { InterviewStatusBadge } from "@/components/candidates/status-badge";
import { Mascot } from "@/components/brand/mascot";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import { candidatesApi, type Candidate } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";

export default function CandidatesPage() {
  const { can } = useAuth();
  const { toast } = useToast();
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<Candidate[] | null>(null);

  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setItems(await candidatesApi.list(search.trim() || undefined));
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : "Не удалось загрузить кандидатов");
      toast({ variant: "destructive", title: error instanceof ApiError ? error.message : "Не удалось загрузить кандидатов" });
    }
  }, [search, toast]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 250);
    return () => clearTimeout(timer);
  }, [load]);

  return (
    <>
      <PageHeader
        title="Кандидаты"
        description="Кандидаты и их интервью."
        actions={can("candidate.write") ? <InviteDialog onInvited={() => void load()} /> : undefined}
      />
      <div className="relative mb-4 max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-4 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Поиск по имени или e-mail"
          aria-label="Поиск кандидатов"
          className="pl-9"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {loadError ? <div className="empty-state" role="alert"><Mascot name="think" /><h2>Не получилось загрузить</h2><p>{loadError}</p><Button variant="outline" onClick={() => void load()}>Попробовать снова</Button></div> : items === null ? (
        <RowsSkeleton />
      ) : items.length === 0 ? (
        <div className="empty-state"><Mascot name={search.trim() ? "think" : "max"} /><h2>{search.trim() ? "Нет результатов" : "Кандидатов пока нет"}</h2><p>{search.trim() ? "Попробуйте другое имя или e-mail." : "Пригласите кандидата со страницы вакансии."}</p></div>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Кандидат</TableHead>
                <TableHead>Интервью</TableHead>
                <TableHead>Последний статус</TableHead>
                <TableHead>Добавлен</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((candidate) => (
                <TableRow key={candidate.id}>
                  <TableCell>
                    <Link href={`/candidates/${candidate.id}`} className="table-row-link font-medium hover:underline">
                      {candidate.full_name}
                    </Link>
                    <div className="text-xs text-muted-foreground">{candidate.email}</div>
                  </TableCell>
                  <TableCell>{candidate.interview_count}</TableCell>
                  <TableCell>
                    {candidate.last_interview_status ? (
                      <InterviewStatusBadge status={candidate.last_interview_status} />
                    ) : (
                      <span className="text-sm text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {new Date(candidate.created_at).toLocaleDateString("ru-RU")}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </>
  );
}
