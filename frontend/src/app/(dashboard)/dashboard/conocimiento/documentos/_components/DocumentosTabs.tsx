"use client";

import { usePathname } from "next/navigation";
import { UnderlineTabs } from "@/components/composed/underline-tabs";

const TABS = [
  { value: "sources", label: "Fuentes", href: "/dashboard/conocimiento/documentos", exact: true },
  { value: "faq", label: "FAQ", href: "/dashboard/conocimiento/documentos/faq" },
] as const;

export function DocumentosTabs() {
  const pathname = usePathname();
  return <UnderlineTabs tabs={[...TABS]} activeValue={pathname} scrollable />;
}
