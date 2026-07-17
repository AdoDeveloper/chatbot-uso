"use client";

import { usePathname } from "next/navigation";
import { UnderlineTabs } from "@/components/composed/underline-tabs";

const TABS = [
  { value: "todas", label: "Todas", href: "/dashboard/conversaciones", exact: true },
  { value: "pendientes", label: "Pendientes", href: "/dashboard/conversaciones/pendientes" },
  { value: "escaladas", label: "Escaladas", href: "/dashboard/conversaciones/escalamientos" },
] as const;

export function ConversacionesTabs() {
  const pathname = usePathname();
  return <UnderlineTabs tabs={[...TABS]} activeValue={pathname} />;
}
