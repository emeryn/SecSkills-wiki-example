interface SkeletonProps {
  className?: string;
}

/** Loading placeholder; announced once by the surrounding region, not per block. */
export function Skeleton({ className = "h-4 w-full" }: SkeletonProps) {
  return <div aria-hidden className={`animate-pulse rounded-sm bg-surface-muted ${className}`} />;
}
