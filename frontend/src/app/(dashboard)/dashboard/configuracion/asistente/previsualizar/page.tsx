"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { PlaygroundTab } from "../../_lib/tabs";
import { useAsistenteForm } from "../_lib/asistente-context";

export default function PrevisualizarPage() {
  const { loadingWidget, widgetForm, widgetConfig } = useAsistenteForm();

  if (loadingWidget) return <Skeleton className="h-[580px] w-full" />;

  return <PlaygroundTab widgetConfig={widgetForm ?? widgetConfig} />;
}
