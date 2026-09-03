"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Logo } from "@/components/brand/logo";
import { legalApi, type LegalDocument } from "@/lib/api/candidates";
import { ApiError } from "@/lib/api/client";

export default function LegalPage() {
  const params = useParams<{ slug: string }>();
  const [document, setDocument] = useState<LegalDocument | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    legalApi
      .get(params.slug)
      .then(setDocument)
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : "Документ недоступен"));
  }, [params.slug]);

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="mx-auto flex h-16 max-w-3xl items-center px-4">
          <Link href="/" aria-label="LeonIT — на главную">
            <Logo size={28} />
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-10">
        {error ? (
          <p className="text-destructive">{error}</p>
        ) : !document ? (
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        ) : (
          <article>
            <p className="text-sm text-muted-foreground">
              Редакция {document.version} · действует с {document.effective_date} · {document.operator}
            </p>
            <div className="legal-markdown mt-6">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{document.markdown}</ReactMarkdown>
            </div>
            <p className="mt-10 border-t pt-4 font-mono text-xs text-muted-foreground">
              SHA-256 текста: {document.hash.slice(0, 12)}…
            </p>
          </article>
        )}
      </main>
    </div>
  );
}
