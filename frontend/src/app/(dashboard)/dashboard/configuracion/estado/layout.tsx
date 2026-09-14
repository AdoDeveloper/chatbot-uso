import { HeartPulse } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { EstadoTabs } from "./_components/EstadoTabs";

export default function EstadoLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <PageHeader
        icon={HeartPulse}
        title="Estado del sistema"
        tip="Salud de los servicios, historial de incidentes, notificaciones y cuotas de uso del sistema."
      />
      <EstadoTabs />
      {children}
    </div>
  );
}
