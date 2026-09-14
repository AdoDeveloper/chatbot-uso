"use client";

import Link from "next/link";
import { Shield, ChevronRight } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { PromptTab, ParamsTab, FloatingSaveBar } from "../../_lib/tabs";
import { useAsistenteForm } from "../_lib/asistente-context";

export default function PromptPage() {
  const { form, set, loadingSettings, isDirty, saving, handleSave, handleDiscard } = useAsistenteForm();

  if (loadingSettings) {
    return (
      <div className="space-y-4 py-8">
        {[1,2,3,4].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
      </div>
    );
  }

  return (
    <>
      <PromptTab form={form} set={set} />
      <div className="my-6 border-t" />
      <ParamsTab form={form} set={set} />
      <div className="my-6 border-t" />
      <div>
        <Link href="/dashboard/configuracion/filtros">
          <div className="flex items-center justify-between px-4 py-3 rounded-xl border border-border bg-card hover:bg-muted/40 transition-colors cursor-pointer group">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                <Shield className="w-4 h-4 text-primary" />
              </div>
              <div>
                <p className="text-13 font-medium text-foreground">Filtros de seguridad</p>
                <p className="text-2xs text-muted-foreground">Filtros de contenido, protección de datos personales y probador de texto</p>
              </div>
            </div>
            <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-foreground transition-colors" />
          </div>
        </Link>
      </div>
      <FloatingSaveBar dirty={isDirty} saving={saving} onSave={handleSave} onDiscard={handleDiscard} />
    </>
  );
}
