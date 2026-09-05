"use client";

import { Eye } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import type { ChatbotSettings, WidgetConfig } from "@/types";
import { PlaygroundTab } from "../_lib/tabs";

export default function PreviewPage() {
 const { loading: loadingSettings } = useApi<ChatbotSettings>("/settings");
 const { data: widgetConfig, loading: loadingWidget } = useApi<WidgetConfig>("/widget/config");

 return (
  <div>
   <PageHeader icon={Eye} title="Vista previa" tip="Prueba el chatbot con los documentos en borrador o solo con los aprobados." />
    {loadingWidget || loadingSettings ? (
     <Skeleton className="h-[580px] w-full" />
    ) : (
     <PlaygroundTab widgetConfig={widgetConfig} />
    )}
  </div>
 );
}
