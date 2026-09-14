"use client";

import { usePathname } from "next/navigation";
import { Activity, ShieldAlert, Syringe } from "lucide-react";
import { UnderlineTabs } from "@/components/composed/underline-tabs";

const TABS = [
  { value: "auditoria", label: "Auditoría", icon: Activity, href: "/dashboard/actividad/auditoria", exact: true },
  { value: "seguridad", label: "Seguridad", icon: ShieldAlert, href: "/dashboard/actividad/seguridad" },
  { value: "inyecciones", label: "Inyecciones", icon: Syringe, href: "/dashboard/actividad/inyecciones" },
] as const;

export function ActividadTabs() {
  const pathname = usePathname();
  return <UnderlineTabs tabs={[...TABS]} activeValue={pathname} scrollable />;
}
