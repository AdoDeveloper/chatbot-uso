"use client";

import { useState } from "react";
import { Plus, CheckCircle, Clock, ExternalLink, Loader2, Search, X } from "lucide-react";
import type { RootCause, UnansweredGroup, UnansweredQuestion } from "@/types";
import Link from "next/link";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/composed/modal";
import { useToast } from "@/components/ui/toast";
import { ConversacionesTabs } from "../_components/ConversacionesTabs";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { formatInProjectTz } from "@/lib/datetime";
import { MessageSquare } from "lucide-react";

interface UnansweredResponse {
  groups: UnansweredGroup[];
  total: number;
}

interface FAQDraftModal {
  question: UnansweredQuestion;
  answer: string;
  saving: boolean;
}

export default function PendientesPage() {
  const { toast } = useToast();
  const { data, loading, refetch: load } = useApi<UnansweredResponse>("/unanswered");
  const [faqModal, setFaqModal] = useState<FAQDraftModal | null>(null);
  const [rootCauseByQid, setRootCauseByQid] = useState<Record<string, RootCause | null>>({});
  const [rootCauseLoading, setRootCauseLoading] = useState<string | null>(null);

  async function loadRootCause(qid: string) {
    if (rootCauseByQid[qid]) {
      setRootCauseByQid((prev) => {
        const next = { ...prev };
        delete next[qid];
        return next;
      });
      return;
    }
    setRootCauseLoading(qid);
    try {
      const { data } = await api.get<RootCause>(`/unanswered/${qid}/root-cause`);
      setRootCauseByQid((prev) => ({ ...prev, [qid]: data }));
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo analizar la causa raíz.") });
    } finally {
      setRootCauseLoading(null);
    }
  }

  async function handleResolve(questionId: string) {
    await api.post(`/unanswered/${questionId}/resolve`);
    toast({ type: "success", message: "Marcada como resuelta." });
    load();
  }

  function openFaqModal(question: UnansweredQuestion) {
    setFaqModal({ question, answer: "", saving: false });
  }

  async function submitFAQ() {
    if (!faqModal || !faqModal.answer.trim()) return;
    setFaqModal((m) => m ? { ...m, saving: true } : null);
    try {
      await api.post(`/unanswered/${faqModal.question.id}/create-faq`, {
        answer: faqModal.answer.trim(),
        tags: faqModal.question.detected_topic ? [faqModal.question.detected_topic] : [],
      });
      toast({ type: "success", message: "FAQ creada y pregunta marcada como resuelta." });
      setFaqModal(null);
      load();
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al crear la FAQ.") });
      setFaqModal((m) => m ? { ...m, saving: false } : null);
    }
  }

  return (
    <div>
      <PageHeader
        icon={MessageSquare}
        title="Conversaciones"
        tip="Historial del chatbot, preguntas sin responder y chats escalados."
      />
      <ConversacionesTabs />
      <div className="mb-4 pb-4 border-b border-border">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold flex-1 min-w-0 truncate">Preguntas pendientes</h2>
        </div>
        <p className="text-2xs text-muted-foreground mt-0.5">
           Consultas que el chatbot no pudo responder, agrupadas por tema. Conviértelas en FAQ
           o márcalas como resueltas tras añadir el contenido fuente correspondiente.
         </p>
      </div>

      {loading ? (
        <div className="space-y-4">
          {[1,2,3].map((g) => (
            <Card key={g}>
              <CardHeader className="flex-row items-center justify-between pb-3">
                <div className="space-y-2">
                  <Skeleton className="h-5 w-48" />
                  <Skeleton className="h-3 w-64" />
                </div>
                <Skeleton className="h-5 w-12" />
              </CardHeader>
              <CardContent>
                <div className="divide-y">
                  {[1,2].map((q) => (
                    <div key={q} className="py-3 space-y-2">
                      <Skeleton className="h-4 w-3/4" />
                      <div className="flex items-center gap-3">
                        <Skeleton className="h-3 w-28" />
                        <Skeleton className="h-3 w-24" />
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : !data || data.total === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <CheckCircle className="w-8 h-8 mx-auto mb-3 text-brand-green/60" />
            <p className="text-13 font-medium text-foreground">¡Todo al día!</p>
            <p className="text-2xs text-muted-foreground mt-1">No hay preguntas sin respuesta en este momento.</p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="mb-4 flex items-center gap-3 text-sm">
            <Badge variant="warning">
              {data.total} pendientes
            </Badge>
            <span className="text-muted-foreground">
              Distribuidas en {data.groups.length} {data.groups.length === 1 ? "tema" : "temas"}
            </span>
          </div>

          <div className="space-y-4">
            {data.groups.map((group) => (
              <Card key={group.topic}>
                <CardHeader className="flex-row items-center justify-between pb-3">
                  <div>
                    <CardTitle className="text-15 font-semibold">{group.topic}</CardTitle>
                    <p className="text-2xs text-muted-foreground mt-0.5">
                      {group.count} {group.count === 1 ? "pregunta" : "preguntas"} ·
                      desde {new Date(group.first_seen).toLocaleDateString("es")}
                    </p>
                  </div>
                  <Badge variant="outline">{group.count}</Badge>
                </CardHeader>
                <CardContent>
                  <div className="divide-y">
                    {group.questions.map((q) => {
                      const rc = rootCauseByQid[q.id];
                      const isLoadingRC = rootCauseLoading === q.id;
                      return (
                        <div key={q.id} className="py-3 space-y-2">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1">
                              <p className="text-sm">{q.question}</p>
                              <div className="flex items-center gap-3 mt-1">
                                <p className="text-2xs text-muted-foreground flex items-center gap-1">
                                  <Clock className="w-3 h-3" />
                                  {formatInProjectTz(q.created_at, { dateStyle: "short", timeStyle: "short" })}
                                </p>
                                {q.conversation_id && (
                                  <Link
                                    href={`/dashboard/conversaciones?id=${q.conversation_id}`}
                                    className="text-xs text-primary hover:underline flex items-center gap-0.5"
                                    title="Ver la conversación original"
                                  >
                                    <ExternalLink className="w-3 h-3" />
                                    Ver conversación
                                  </Link>
                                )}
                              </div>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => loadRootCause(q.id)}
                                disabled={isLoadingRC}
                                className="gap-1.5 text-xs"
                                title="Analizar por qué el bot no respondió"
                              >
                                {isLoadingRC
                                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  : <Search className="w-3.5 h-3.5" />}
                                Causa raíz
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => openFaqModal(q)}
                                className="gap-1.5 text-xs"
                                title="Convertir esta pregunta en una FAQ con respuesta"
                              >
                                <Plus className="w-3.5 h-3.5" /> Crear FAQ
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleResolve(q.id)}
                                className="gap-1.5 text-xs"
                                title="Marcar como resuelta sin crear FAQ"
                              >
                                <CheckCircle className="w-3.5 h-3.5" />
                              </Button>
                            </div>
                          </div>
                          {rc && (
                            <div className="ml-4 pl-3 border-l-2 border-primary/30 bg-muted/30 rounded-r p-2 space-y-1.5">
                              <p className="text-3xs uppercase tracking-wider text-muted-foreground font-semibold">Análisis automático</p>
                              {rc.causes.map((c) => (
                                <div key={c.code} className="text-xs">
                                  <Badge variant="warning" size="xs" className="mr-2">{c.label}</Badge>
                                  <span className="text-muted-foreground">{c.detail}</span>
                                </div>
                              ))}
                              {rc.suggestions.length > 0 && (
                                <div className="pt-1 border-t border-border/50">
                                  <p className="text-3xs uppercase tracking-wider text-muted-foreground font-semibold mb-1">Sugerencias</p>
                                  <ul className="text-xs text-foreground space-y-0.5 list-disc pl-4">
                                    {rc.suggestions.map((s, i) => <li key={i}>{s}</li>)}
                                  </ul>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}

      {/* FAQ creation dialog */}
      <Modal
        open={!!faqModal}
        onClose={() => setFaqModal(null)}
        size="lg"
        title="Crear FAQ"
        footer={
          <>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setFaqModal(null)} disabled={faqModal?.saving}>
              <X className="w-3.5 h-3.5" /> Cancelar
            </Button>
            <Button
              size="sm"
              className="gap-1.5"
              onClick={submitFAQ}
              disabled={!faqModal?.answer.trim() || faqModal?.saving}
            >
              {faqModal?.saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
              {faqModal?.saving ? "Creando..." : "Crear FAQ"}
            </Button>
          </>
        }
      >
        <div className="space-y-4 pt-1">
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">Pregunta</p>
            <p className="text-sm bg-card rounded-lg px-3 py-2 border border-border">
              {faqModal?.question.question}
            </p>
          </div>
          <div>
            <label className="block text-xs font-medium text-foreground mb-1">
              Respuesta <span className="text-destructive">*</span>
            </label>
            <Textarea
              rows={5}
              placeholder="Escribe la respuesta que el chatbot usará para esta pregunta..."
              value={faqModal?.answer ?? ""}
              onChange={(e) => setFaqModal((m) => m ? { ...m, answer: e.target.value } : null)}
              className="resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}
