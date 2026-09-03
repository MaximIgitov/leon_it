"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Loader2, Search, Users } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { InviteDialog } from "@/components/candidates/invite-dialog";
import { InterviewStatusBadge } from "@/components/candidates/status-badge";
import { PageHeader } from "@/components/layout/page-header";
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

  const load = useCallback(async () => {
    try {
      setItems(await candidatesApi.list(search.trim() || undefined));
    } catch (error) {
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
        description="Все, кого приглашали на интервью. Один кандидат может проходить несколько вакансий."
        actions={can("candidate.write") ? <InviteDialog onInvited={() => void load()} /> : undefined}
      />
      <div className="relative mb-4 max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Поиск по имени или e-mail"
          className="pl-9"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
      {items === null ? (
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dashed p-10 text-center">
          <Users className="mx-auto h-8 w-8 text-muted-foreground" />
          <p className="mt-3 font-medium">Кандидатов пока нет</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Пригласите первого — по одному или списком из вставленного текста.
          </p>
        </div>
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
                    <Link href={`/candidates/${candidate.id}`} className="font-medium hover:underline">
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
