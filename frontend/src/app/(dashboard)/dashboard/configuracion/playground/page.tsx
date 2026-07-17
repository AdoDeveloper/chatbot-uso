"use client";

import { Eye } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import type { ChatbotSettings, WidgetConfig } from "@/types";
import { PlaygroundTab, SETTINGS_DEFAULTS } from "../_lib/tabs";

export default function PreviewPage() {
 const { data: settingsData, loading: loadingSettings } = useApi<ChatbotSettings>("/settings");
 const { data: widgetConfig, loading: loadingWidget } = useApi<WidgetConfig>("/widget/config");
 const { data: deployedData, loading: loadingDeployed } = useApi<WidgetConfig>("/versions/deploy/config");

 const settings = settingsData ?? SETTINGS_DEFAULTS;
 const deployedWidgetConfig = deployedData && Object.keys(deployedData).length > 0 ? deployedData : null;

 return (
  <div>
   <PageHeader icon={Eye} title="Vista previa" tip="Prueba el chatbot en entorno de pruebas o con la última versión en producción." />
    {loadingWidget || loadingDeployed || loadingSettings ? (
     <Skeleton className="h-[580px] w-full" />
    ) : (
     <PlaygroundTab
      settings={settings}
      savedSettings={settings}
      widgetConfig={widgetConfig}
      deployedWidgetConfig={deployedWidgetConfig}
     />
    )}
  </div>
 );
}
