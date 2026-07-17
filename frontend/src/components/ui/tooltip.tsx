"use client";

import * as React from "react";
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";
import { cn } from "@/lib/utils";

function TooltipProvider({
  delayDuration = 0,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider> & { delayDuration?: number }) {
  return (
    <TooltipPrimitive.Provider delay={delayDuration} {...props}>
      {children}
    </TooltipPrimitive.Provider>
  );
}

function TooltipRoot({ children, ...props }: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return <TooltipPrimitive.Root {...props}>{children}</TooltipPrimitive.Root>;
}

function TooltipTrigger({
  asChild,
  children,
  ...props
}: Omit<React.ComponentProps<typeof TooltipPrimitive.Trigger>, "render"> & {
  asChild?: boolean;
}) {
  if (asChild && React.isValidElement(children)) {
    return <TooltipPrimitive.Trigger render={children} {...props} />;
  }
  return <TooltipPrimitive.Trigger {...props}>{children}</TooltipPrimitive.Trigger>;
}

function TooltipContent({
  className,
  sideOffset = 4,
  hidden,
  side,
  align,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Popup> & {
  sideOffset?: number;
  hidden?: boolean;
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
}) {
  if (hidden) return null;
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Positioner sideOffset={sideOffset} side={side} align={align}>
        <TooltipPrimitive.Popup
          className={cn(
            "z-50 overflow-hidden rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground shadow-md animate-in fade-in-0 zoom-in-95",
            className
          )}
          {...props}
        >
          {children}
        </TooltipPrimitive.Popup>
      </TooltipPrimitive.Positioner>
    </TooltipPrimitive.Portal>
  );
}

// Existing call sites use <Tooltip content="..." side="..."><trigger/></Tooltip>.
// Keep that working so we don't break ImagenesTab.tsx and similar.
function Tooltip({
  content,
  children,
  side = "top",
  className,
}: {
  content?: React.ReactNode;
  children: React.ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  className?: string;
}) {
  if (content === undefined) {
    // Used as a Radix-style root: <Tooltip><TooltipTrigger/><TooltipContent/></Tooltip>
    return <TooltipRoot>{children}</TooltipRoot>;
  }
  return (
    <TooltipRoot>
      <TooltipPrimitive.Trigger render={<span className="inline-flex" />}>{children}</TooltipPrimitive.Trigger>
      <TooltipContent side={side} className={className}>
        {content}
      </TooltipContent>
    </TooltipRoot>
  );
}

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
