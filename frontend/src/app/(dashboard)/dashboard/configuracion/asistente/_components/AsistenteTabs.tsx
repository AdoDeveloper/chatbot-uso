"use client";

import { usePathname } from "next/navigation";
import { Bot, Palette, Code2, Gauge, Eye } from "lucide-react";
import { UnderlineTabs } from "@/components/composed/underline-tabs";

const TABS = [
  { value: "apariencia", label: "Apariencia", icon: Palette, href: "/dashboard/configuracion/asistente/apariencia", exact: true },
  { value: "prompt", label: "Prompt", icon: Bot, href: "/dashboard/configuracion/asistente/prompt" },
  { value: "integracion", label: "Integración", icon: Code2, href: "/dashboard/configuracion/asistente/integracion" },
  { value: "limites", label: "Límites", icon: Gauge, href: "/dashboard/configuracion/asistente/limites" },
  { value: "previsualizar", label: "Previsualizar", icon: Eye, href: "/dashboard/configuracion/asistente/previsualizar" },
] as const;

export function AsistenteTabs() {
  const pathname = usePathname();
  return <UnderlineTabs tabs={[...TABS]} activeValue={pathname} scrollable />;
}
