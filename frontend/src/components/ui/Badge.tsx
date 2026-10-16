import type { ReactNode } from "react";

type Tone = "neutral" | "success" | "danger" | "primary";

const TONES: Record<Tone, string> = {
  neutral: "border-border text-text-muted",
  success: "border-success/40 text-success",
  danger: "border-danger/40 text-danger",
  primary: "border-primary/40 text-primary",
};

/** Status label; the text always carries the meaning (never color alone). */
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-sm border px-1.5 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
