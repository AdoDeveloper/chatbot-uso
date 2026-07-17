import type { LucideIcon } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";

interface PageShellProps {
  title: string;
  description?: string;
  icon?: LucideIcon;
  badge?: React.ReactNode;
  /** Acciones principales de la vista (cabecera, arriba-derecha). */
  action?: React.ReactNode;
  /** Contenido de la página. Se separa con space-y-6 por defecto. */
  children: React.ReactNode;
  className?: string;
  /** Contenido a renderer antes de la cabecera (banners globales, paneles). */
  before?: React.ReactNode;
}

/**
 * Contenedor estándar de una vista del panel. Impone el ritmo vertical
 * (space-y-6) y la cabecera consistente vía PageHeader, para que ninguna
 * página vuelva a elegir su propio espaciado o maquetar su cabecera a mano.
 *
 * El padding lateral lo aporta el layout del dashboard; PageShell solo
 * gobierna el ritmo interno y la cabecera.
 */
export function PageShell({
  title, description, icon, badge, action, children, className, before,
}: PageShellProps) {
  return (
    <div className={className}>
      {before}
      {/* PageHeader aporta su propio margen inferior (mb-6 pb-5 border-b). */}
      <PageHeader title={title} description={description} icon={icon} badge={badge} action={action} />
      <div className="space-y-6">{children}</div>
    </div>
  );
}
