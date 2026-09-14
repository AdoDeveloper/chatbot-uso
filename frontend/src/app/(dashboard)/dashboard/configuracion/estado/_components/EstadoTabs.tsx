"use client";

import { usePathname } from "next/navigation";
import { HeartPulse, Activity } from "lucide-react";
import { UnderlineTabs } from "@/components/composed/underline-tabs";

const TABS = [
  { value: "estado", label: "Estado", icon: HeartPulse, href: "/dashboard/configuracion/estado", exact: true },
  { value: "cuotas", label: "Cuotas", icon: Activity, href: "/dashboard/configuracion/estado/cuotas" },
] as const;

export function EstadoTabs() {
  const pathname = usePathname();
  return <UnderlineTabs tabs={[...TABS]} activeValue={pathname} scrollable />;
}
