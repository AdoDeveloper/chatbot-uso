"use client";

import { useRouter } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { WidgetTab } from "../../_lib/tabs";
import { useAsistenteForm } from "../_lib/asistente-context";

export default function LimitesPage() {
  const router = useRouter();
  const { loadingSettings, loadingWidget, widgetForm, setWidgetForm } = useAsistenteForm();

  if (loadingSettings || loadingWidget) {
    return (
      <div className="space-y-4 py-8">
        {[1,2,3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
      </div>
    );
  }

  return (
    <WidgetTab
      subtab="limites"
      onPreview={() => router.push("/dashboard/configuracion/asistente/previsualizar")}
      config={widgetForm}
      setConfig={setWidgetForm}
    />
  );
}
