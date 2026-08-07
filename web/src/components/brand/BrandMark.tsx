import { cn } from "@/lib/utils";

interface BrandMarkProps {
  className?: string;
  inverted?: boolean;
}

export function BrandMark({ className, inverted = false }: BrandMarkProps) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px]",
        inverted ? "bg-white/10 text-white" : "bg-[var(--merchant-navy)] text-white",
        className
      )}
    >
      <svg viewBox="0 0 32 32" className="h-7 w-7" fill="none">
        <path d="M6 20.5 16 10l10 10.5" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        <path d="M8 23h16" stroke="var(--merchant-cyan)" strokeWidth="3" strokeLinecap="round" />
        <path d="M11 18v5M21 18v5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
    </span>
  );
}
