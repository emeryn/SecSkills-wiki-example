import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
}

/** Short explanation plus at most one primary action. */
export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border px-6 py-8 text-center">
      <Icon aria-hidden className="size-6 text-text-muted" />
      <p className="font-medium">{title}</p>
      <p className="text-text-muted">{description}</p>
      {action !== undefined && <div className="mt-2">{action}</div>}
    </div>
  );
}
