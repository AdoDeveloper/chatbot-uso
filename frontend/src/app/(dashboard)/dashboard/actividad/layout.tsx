import { Activity } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { ActividadTabs } from "./_components/ActividadTabs";

export default function ActividadLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <PageHeader
        icon={Activity}
        title="Actividad"
        tip="Acciones admin, intentos de ataque y prompts bloqueados por guardrails."
      />
      <ActividadTabs />
      {children}
    </div>
  );
}
