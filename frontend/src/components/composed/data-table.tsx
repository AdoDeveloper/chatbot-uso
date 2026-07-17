"use client";

import { Fragment, type ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableHeader, TableBody, TableHead, TableRow } from "@/components/ui/table";
import { TablePagination } from "@/components/composed/table-pagination";

export interface Column {
  id: string;
  header: ReactNode;
  className?: string;
  hideBelow?: "sm" | "md" | "lg";
  sticky?: boolean;
  sortable?: boolean;
  onSort?: () => void;
  sortIcon?: ReactNode;
}

interface DataTableProps<T> {
  columns?: Column[];
  data?: T[];
  rowKey?: (item: T) => string;
  renderRow?: (item: T) => ReactNode;
  loading?: boolean;
  empty?: ReactNode;
  skeleton?: ReactNode;
  className?: string;
  pagination?: {
    page: number;
    pageSize: number;
    total: number;
    onPageChange: (page: number) => void;
    onPageSizeChange?: (size: number) => void;
    itemLabel?: string;
  };
  noCard?: boolean;
  children?: ReactNode;
}

export function DataTable<T>({
  columns, data, rowKey, renderRow,
  loading = false,
  empty,
  skeleton,
  className,
  pagination,
  noCard,
  children,
}: DataTableProps<T>) {
  const content = loading ? (
    skeleton ?? (
      <div className="space-y-3 p-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-12 w-full rounded-lg" />
        ))}
      </div>
    )
  ) : children != null || (data != null && data.length > 0) ? (
    <>
      <div className="overflow-x-auto">
        <Table>
          {columns && (
            <TableHeader>
              <TableRow>
                {columns.map((col) => {
                  const hideClass = col.hideBelow === "sm" ? "hidden sm:table-cell"
                    : col.hideBelow === "md" ? "hidden md:table-cell"
                    : col.hideBelow === "lg" ? "hidden lg:table-cell"
                    : "";
                  return (
                    <TableHead
                      key={col.id}
                      className={`${hideClass} ${col.className ?? ""}`}
                      sticky={col.sticky}
                      onClick={col.sortable ? col.onSort : undefined}
                    >
                      {col.sortable ? (
                        <span className="inline-flex items-center gap-1 cursor-pointer select-none hover:text-foreground">
                          {col.header} {col.sortIcon}
                        </span>
                      ) : (
                        col.header
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            </TableHeader>
          )}
          <TableBody>
            {children ?? (data && rowKey && renderRow
              ? data.map((item) => <Fragment key={rowKey(item)}>{renderRow(item)}</Fragment>)
              : null)}
          </TableBody>
        </Table>
      </div>
      {pagination && (
        <TablePagination
          total={pagination.total}
          page={pagination.page}
          pageSize={pagination.pageSize}
          onPageChange={pagination.onPageChange}
          onPageSizeChange={pagination.onPageSizeChange}
          itemLabel={pagination.itemLabel}
        />
      )}
    </>
  ) : empty ? (
    empty
  ) : null;

  if (noCard) return <div className={className}>{content}</div>;
  return <Card className={`overflow-hidden ${className ?? ""}`}>{content}</Card>;
}
