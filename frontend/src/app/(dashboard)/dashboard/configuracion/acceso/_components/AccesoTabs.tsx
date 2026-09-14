"use client";

import { usePathname } from "next/navigation";
import { UnderlineTabs } from "@/components/composed/underline-tabs";

const TABS = [
  { value: "usuarios", label: "Usuarios", href: "/dashboard/configuracion/acceso/usuarios", exact: true },
  { value: "sso", label: "SSO", href: "/dashboard/configuracion/acceso/sso" },
] as const;

export function AccesoTabs() {
  const pathname = usePathname();
  return <UnderlineTabs tabs={[...TABS]} activeValue={pathname} scrollable />;
}
