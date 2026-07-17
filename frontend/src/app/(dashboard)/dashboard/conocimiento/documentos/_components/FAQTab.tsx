"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, Plus, Pencil, Trash2, Check, Tag, Loader2, Search, X } from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import type { FAQEntry } from "@/types";
import { useToast } from "@/components/ui/toast";

import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { SegmentedControl } from "@/components/composed/segmented-control";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Modal } from "@/components/composed/modal";
import { TableCell, TableRow } from "@/components/ui/table";
import { DataTable } from "@/components/composed/data-table";

// Tab "FAQ" dentro de Documentos. Se accede vía /conocimiento/documentos?tab=faq;
// el header de página lo aporta la página padre Documentos.

interface FAQForm {
  question: string;
  answer: string;
  tags: string;
  is_active: boolean;
}

const EMPTY_FORM: FAQForm = { question: "", answer: "", tags: "", is_active: true };

type StateFilter = "all" | "active" | "inactive";

export default function FAQTab() {
  const { toast } = useToast();
  const { data: entriesData, loading, error: entriesError, refetch: load } = useApi<FAQEntry[]>("/faq");
  const entries = useMemo(() => entriesData ?? [], [entriesData]);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<FAQEntry | null>(null);
  const [form, setForm] = useState<FAQForm>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<FAQEntry | null>(null);

  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<StateFilter>("all");
  const [activeTag, setActiveTag] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  useEffect(() => {
    if (entriesError) toast({ type: "error", message: "No se pudo cargar la lista de FAQs." });
  }, [entriesError, toast]);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    entries.forEach((e) => e.tags.forEach((t) => set.add(t)));
    return Array.from(set).sort();
  }, [entries]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return entries.filter((e) => {
      if (stateFilter === "active" && !e.is_active) return false;
      if (stateFilter === "inactive" && e.is_active) return false;
      if (activeTag && !e.tags.includes(activeTag)) return false;
      if (q) {
        const hay = (e.question + " " + e.answer + " " + e.tags.join(" ")).toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [entries, search, stateFilter, activeTag]);

  useEffect(() => { setPage(1); }, [search, stateFilter, activeTag]);

  const paginated = useMemo(
    () => filtered.slice((page - 1) * pageSize, page * pageSize),
    [filtered, page, pageSize]
  );

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setShowModal(true);
  }

  function openEdit(entry: FAQEntry) {
    setEditing(entry);
    setForm({ question: entry.question, answer: entry.answer, tags: entry.tags.join(", "), is_active: entry.is_active });
    setShowModal(true);
  }

  async function handleSave() {
    if (!form.question.trim() || !form.answer.trim()) return;
    setSaving(true);
    const payload = {
      question: form.question.trim(),
      answer: form.answer.trim(),
      tags: form.tags.split(",").map((t) => t.trim()).filter(Boolean),
      is_active: form.is_active,
    };
    try {
      if (editing) {
        await api.patch(`/faq/${editing.id}`, payload);
      } else {
        await api.post("/faq", payload);
      }
      toast({ type: "success", message: editing ? "Entrada actualizada." : "Entrada FAQ creada." });
      setShowModal(false);
      load();
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar la entrada. Inténtelo de nuevo.") });
    } finally {
      setSaving(false);
    }
  }

  async function confirmAndDelete() {
    if (!confirmDelete) return;
    const id = confirmDelete.id;
    setDeleting(id);
    setConfirmDelete(null);
    try {
      await api.delete(`/faq/${id}`);
      toast({ type: "success", message: "Entrada eliminada." });
      load();
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo eliminar la entrada.") });
    } finally {
      setDeleting(null);
    }
  }

  const stats = useMemo(() => ({
    total: entries.length,
    active: entries.filter((e) => e.is_active).length,
    inactive: entries.filter((e) => !e.is_active).length,
  }), [entries]);

  return (
    <div>
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 px-5 py-4 border-b border-border/60">
          <p className="text-sm text-muted-foreground">
            Pares pregunta/respuesta que el chatbot usa como conocimiento directo.
          </p>
          <div className="grid grid-cols-1 sm:flex sm:justify-end gap-2">
            <Button onClick={openCreate} size="sm" className="gap-1.5">
              <Plus className="w-3.5 h-3.5" aria-hidden="true" /> Nueva entrada
            </Button>
          </div>
        </div>

        <div className="flex flex-col lg:flex-row lg:items-center gap-3 px-5 pt-4">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" aria-hidden="true" />
            <Input
              className="pl-8 h-9"
              placeholder="Buscar por pregunta, respuesta o tag..."
              aria-label="Buscar FAQ"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <SegmentedControl
            ariaLabel="Filtrar por estado"
            variant="chip"
            value={stateFilter}
            onChange={setStateFilter}
            options={[
              { value: "all" as StateFilter, label: `Todas (${stats.total})` },
              { value: "active" as StateFilter, label: `Activas (${stats.active})` },
              { value: "inactive" as StateFilter, label: `Inactivas (${stats.inactive})` },
            ]}
          />
        </div>

        {allTags.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 px-5 pt-4">
            <span className="text-2xs text-muted-foreground mr-1">Tags:</span>
            {activeTag && (
              <button
                type="button"
                onClick={() => setActiveTag(null)}
                className="inline-flex items-center gap-1 h-6 px-2 text-2xs rounded-full bg-muted text-muted-foreground hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                aria-label="Limpiar filtro de tag"
              >
                <X className="w-3 h-3" aria-hidden="true" /> Limpiar
              </button>
            )}
            {allTags.slice(0, 20).map((tag) => {
              const active = activeTag === tag;
              return (
                <button
                  key={tag}
                  type="button"
                  onClick={() => setActiveTag(active ? null : tag)}
                  aria-pressed={active}
                  className={`inline-flex items-center gap-1 h-6 px-2 text-2xs rounded-full border transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 ${
                    active
                      ? "bg-primary/10 text-primary border-primary/40"
                      : "bg-background text-muted-foreground border-border hover:bg-muted"
                  }`}
                >
                  <Tag className="w-3 h-3" aria-hidden="true" /> {tag}
                </button>
              );
            })}
            {allTags.length > 20 && (
              <span className="text-2xs text-muted-foreground">+{allTags.length - 20} más</span>
            )}
          </div>
        )}

        <DataTable
          loading={loading}
          skeleton={<CardContent className="py-6 space-y-3">{[1,2,3,4].map(i => <Skeleton key={i} className="h-12 w-full" />)}</CardContent>}
          empty={
            entries.length === 0 ? (
              <CardContent><EmptyState icon={BookOpen} title="Sin entradas de FAQ" description="Crea pares de pregunta/respuesta para el chatbot." /></CardContent>
            ) : (
              <CardContent><EmptyState icon={Search} title="Sin resultados" description="Ningún item coincide con los filtros aplicados." /></CardContent>
            )
          }
          pagination={{ page, pageSize, total: filtered.length, onPageChange: setPage, onPageSizeChange: (n) => { setPageSize(n); setPage(1); }, itemLabel: "entradas" }}
          noCard
          columns={[
            { id: "pregunta", header: "Pregunta", className: "w-[280px]" },
            { id: "respuesta", header: "Respuesta", hideBelow: "lg" },
            { id: "tags", header: "Tags", className: "w-[180px]", hideBelow: "md" },
            { id: "estado", header: "Estado", className: "w-[90px]", hideBelow: "sm" },
            { id: "acciones", header: "Acciones", className: "w-[80px] text-right", sticky: true },
          ]}
          data={paginated}
          rowKey={(entry) => entry.id}
          renderRow={(entry) => (
            <TableRow>
              <TableCell className="font-medium text-sm align-top">
                <p className="line-clamp-2">{entry.question}</p>
              </TableCell>
              <TableCell className="text-sm text-muted-foreground align-top hidden lg:table-cell">
                <p className="line-clamp-2">{entry.answer}</p>
              </TableCell>
              <TableCell className="align-top hidden md:table-cell">
                <div className="flex flex-wrap gap-1">
                  {entry.tags.slice(0, 3).map((tag) => (
                    <button
                      key={tag}
                      type="button"
                      onClick={() => setActiveTag(tag)}
                      className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 rounded-full"
                      aria-label={`Filtrar por tag ${tag}`}
                    >
                      <Badge variant="secondary" className="text-3xs gap-0.5 cursor-pointer hover:bg-secondary/80">
                        <Tag className="w-3 h-3" aria-hidden="true" />{tag}
                      </Badge>
                    </button>
                  ))}
                  {entry.tags.length > 3 && (
                    <span className="text-3xs text-muted-foreground self-center">+{entry.tags.length - 3}</span>
                  )}
                </div>
              </TableCell>
              <TableCell className="align-top hidden sm:table-cell">
                <Badge variant={entry.is_active ? "success" : "secondary"} className="text-3xs">
                  {entry.is_active ? "Activo" : "Inactivo"}
                </Badge>
              </TableCell>
              <TableCell className="align-top" sticky>
                <div className="flex items-center gap-1 justify-end">
                  <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground" onClick={() => openEdit(entry)} aria-label={`Editar "${entry.question.slice(0, 40)}"`}>
                    <Pencil className="w-3.5 h-3.5" aria-hidden="true" />
                  </Button>
                  <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" onClick={() => setConfirmDelete(entry)} disabled={deleting === entry.id} aria-label={`Eliminar "${entry.question.slice(0, 40)}"`}>
                    {deleting === entry.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> : <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />}
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          )}
        />
      </Card>

      <Modal
        open={showModal}
        onClose={() => setShowModal(false)}
        title={editing ? "Editar entrada" : "Nueva entrada FAQ"}
        size="lg"
        footer={
          <>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setShowModal(false)}><X className="w-3.5 h-3.5" /> Cancelar</Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saving || !form.question.trim() || !form.answer.trim()}
              className="gap-1.5"
            >
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" /> : <Check className="w-3.5 h-3.5" aria-hidden="true" />}
              Guardar
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="faq-question" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pregunta</Label>
            <Input
              id="faq-question"
              value={form.question}
              onChange={(e) => setForm((f) => ({ ...f, question: e.target.value }))}
              placeholder="¿Cuál es el proceso de inscripción?"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="faq-answer" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Respuesta</Label>
            <textarea
              id="faq-answer"
              value={form.answer}
              onChange={(e) => setForm((f) => ({ ...f, answer: e.target.value }))}
              rows={4}
              placeholder="El proceso de inscripción consiste en..."
              className="w-full px-3 py-2 bg-background border border-input rounded-md text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring/50 focus:border-ring placeholder:text-muted-foreground"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="faq-tags" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Tags <span className="normal-case font-normal">(separados por coma)</span>
            </Label>
            <Input
              id="faq-tags"
              value={form.tags}
              onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))}
              placeholder="becas, inscripción, admisión"
            />
          </div>
          <div className="flex items-center gap-3 rounded-lg border px-3 py-2.5 bg-muted/30">
            <Switch
              id="faq-active"
              checked={form.is_active}
              onCheckedChange={(checked) => setForm((f) => ({ ...f, is_active: checked }))}
            />
            <Label htmlFor="faq-active" className="cursor-pointer">
              <p className="text-13 font-medium">Entrada activa</p>
              <p className="text-2xs text-muted-foreground font-normal">El chatbot utilizará esta entrada en sus respuestas</p>
            </Label>
          </div>
        </div>
      </Modal>

      <Modal
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        title="Eliminar entrada"
        size="sm"
        footer={
          <>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setConfirmDelete(null)}><X className="w-3.5 h-3.5" /> Cancelar</Button>
            <Button variant="destructive" size="sm" className="gap-1.5" onClick={confirmAndDelete}><Trash2 className="w-3.5 h-3.5" /> Eliminar</Button>
          </>
        }
      >
        <p className="text-sm text-muted-foreground">
          ¿Eliminar permanentemente esta entrada? Esta acción no se puede deshacer.
        </p>
        {confirmDelete && (
          <p className="mt-3 text-13 font-medium border-l-2 border-destructive pl-3 line-clamp-2">
            {confirmDelete.question}
          </p>
        )}
      </Modal>
    </div>
  );
}
