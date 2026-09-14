"use client";

import { usePathname } from "next/navigation";
import { UnderlineTabs } from "@/components/composed/underline-tabs";

const TABS = [
  { value: "limites", label: "Límites", href: "/dashboard/configuracion/estado/cuotas/limites", exact: true },
  { value: "tendencia", label: "Tendencia", href: "/dashboard/configuracion/estado/cuotas/tendencia" },
] as const;

export function CuotasTabs() {
  const pathname = usePathname();
  return <UnderlineTabs tabs={[...TABS]} activeValue={pathname} scrollable />;
}
