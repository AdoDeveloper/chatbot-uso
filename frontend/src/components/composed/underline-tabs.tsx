"use client";

import Link from "next/link";
import { ScrollShadow } from "@/components/composed/scroll-shadow";
import type { LucideIcon } from "lucide-react";

interface TabBase {
  value: string;
  label: string;
  icon?: LucideIcon;
}

interface LinkTab extends TabBase {
  href: string;
  exact?: boolean;
}

interface ButtonTab extends TabBase {
  onClick: () => void;
}

type TabConfig = LinkTab | ButtonTab;

interface UnderlineTabsProps {
  tabs: TabConfig[];
  activeValue: string;
  scrollable?: boolean;
  className?: string;
}

export function UnderlineTabs({ tabs, activeValue, scrollable, className }: UnderlineTabsProps) {
  const content = (
    <div role="tablist" className="flex items-center gap-0">
      {tabs.map((tab) => {
        const active = "href" in tab
          ? tab.exact ? activeValue === tab.href : activeValue.startsWith(tab.href)
          : activeValue === tab.value;
        const Icon = tab.icon;
        const sharedClasses = `inline-flex items-center justify-center gap-1.5 whitespace-nowrap text-sm font-medium px-4 py-2.5 border-b-2 -mb-px transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 ${
          active
            ? "border-primary text-primary"
            : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
        }`;

        if ("href" in tab) {
          return (
            <Link
              key={tab.href}
              href={tab.href}
              role="tab"
              aria-selected={active}
              className={sharedClasses}
            >
              {Icon && <Icon className="w-3.5 h-3.5" />}
              {tab.label}
            </Link>
          );
        }

        return (
          <button
            key={tab.value}
            onClick={tab.onClick}
            role="tab"
            aria-selected={active}
            className={sharedClasses}
          >
            {Icon && <Icon className="w-3.5 h-3.5" />}
            {tab.label}
          </button>
        );
      })}
    </div>
  );

  const wrapper = (children: React.ReactNode) => scrollable
    ? <ScrollShadow fadeFrom="background">{children}</ScrollShadow>
    : children;

  return (
    <div className={`border-b border-border mb-6 ${className ?? ""}`}>
      {wrapper(content)}
    </div>
  );
}
