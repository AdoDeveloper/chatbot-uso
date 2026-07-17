"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, ShieldAlert, Syringe } from "lucide-react";
import { UnderlineTabs } from "@/components/composed/underline-tabs";
import { AuditoriaTab } from "../configuracion/_components/AuditoriaTab";
import { SeguridadTab } from "../configuracion/_components/SeguridadTab";
import { useApi } from "@/hooks/use-api";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { formatInProjectTz } from "@/lib/datetime";

const TABS = [
  { value: "auditoria", label: "Auditoría", icon: Activity },
  { value: "seguridad", label: "Seguridad", icon: ShieldAlert },
  { value: "inyecciones", label: "Inyecciones", icon: Syringe },
] as const;

type TabId = typeof TABS[number]["value"];

interface InjectionLogEntry {
  id: string;
  action: string;
  ip: string | null;
  meta_json: { reason?: string; pattern?: string; question_preview?: string } & Record<string, unknown>;
  created_at: string;
}

function InyeccionesContent() {
  const { toast } = useToast();
  const { data, loading, error } = useApi<InjectionLogEntry[]>("/guardrails/injection-log?page_size=50");
  const events = error ? [] : (data ?? []);

  useEffect(() => {
    if (error) toast({ type: "error", message: "No se pudo cargar el log de inyecciones." });
  }, [error, toast]);

  return (
    <>
      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <div className="flex flex-col gap-3 mb-4">
              <p className="text-13 text-muted-foreground">
                Prompts bloqueados por los filtros de inyección. Para ver y editar los
                patrones, ir a <strong>Configuración → Filtros</strong>.
              </p>
            </div>
            <div className="divide-y">
              {[1,2,3,4,5].map((i) => (
                <div key={i} className="py-2.5 flex items-start gap-3">
                  <Skeleton className="w-4 h-4 rounded shrink-0 mt-0.5" />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <Skeleton className="h-4 w-1/2" />
                    <Skeleton className="h-3 w-40" />
                    <Skeleton className="h-3 w-2/3" />
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : (
      <Card>
        <CardContent className="pt-6">
        <div className="flex flex-col gap-3 mb-4">
          <p className="text-13 text-muted-foreground">
            Prompts bloqueados por los filtros de inyección. Para ver y editar los
            patrones, ir a <strong>Configuración → Filtros</strong>.
          </p>
        </div>

        {events.length === 0 ? (
          <EmptyState
            icon={ShieldAlert}
            title="Sin inyecciones registradas"
            description="No hay prompts bloqueados en el periodo reciente."
            className="py-10"
          />
        ) : (
          <div className="divide-y">
            {events.map((ev) => (
              <div key={ev.id} className="py-2.5 flex items-start gap-3">
                <ShieldAlert className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                <div className="min-w-0 flex-1">
                  <p className="text-13 font-medium">{ev.meta_json?.reason ?? "Inyección detectada"}</p>
                  <p className="text-2xs text-muted-foreground mt-0.5 truncate">
                    IP {ev.ip ?? "—"} · {formatInProjectTz(ev.created_at)}
                  </p>
                  {ev.meta_json?.question_preview && (
                    <p className="text-2xs text-muted-foreground mt-1 italic line-clamp-2">
                      {ev.meta_json.question_preview}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
    )}
    </>
  );
}

function isTabId(value: string | null): value is TabId {
  return TABS.some((t) => t.value === value);
}

export default function ActividadPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialTab = searchParams.get("tab");
  const [tab, setTab] = useState<TabId>(isTabId(initialTab) ? initialTab : "auditoria");

  useEffect(() => {
    const urlTab = searchParams.get("tab");
    if (isTabId(urlTab) && urlTab !== tab) setTab(urlTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function selectTab(value: TabId) {
    setTab(value);
    router.replace(`/dashboard/actividad?tab=${value}`, { scroll: false });
  }

  return (
    <div>
      <PageHeader
        icon={Activity}
        title="Actividad"
        tip="Acciones admin, intentos de ataque y prompts bloqueados por guardrails."
      />

      <UnderlineTabs
        tabs={TABS.map((t) => ({ ...t, onClick: () => selectTab(t.value) }))}
        activeValue={tab}
      />

      {tab === "auditoria" && <AuditoriaTab />}
      {tab === "seguridad" && <SeguridadTab />}
      {tab === "inyecciones" && <InyeccionesContent />}
    </div>
  );
}
