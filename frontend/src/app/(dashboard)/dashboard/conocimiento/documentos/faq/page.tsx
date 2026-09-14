"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";

const TabLoading = () => <div className="space-y-4 py-8">{[1,2,3].map(i => <Skeleton key={i} className="h-16 w-full" />)}</div>;

const FAQTab = dynamic(
  () => import("../_components/FAQTab").catch(
    () => {
      const FAQFallback = () => (
        <div className="py-12 text-center text-muted-foreground">FAQ no disponible</div>
      );
      return FAQFallback;
    }
  ),
  { loading: TabLoading }
);

export default function FAQPage() {
  return <FAQTab />;
}
