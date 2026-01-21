'use client';

import { Loader2 } from "lucide-react";

type SpinnerProps = {
  size?: "sm" | "md" | "lg";
  label?: string;
  className?: string;
};

const sizeMap: Record<NonNullable<SpinnerProps["size"]>, string> = {
  sm: "w-4 h-4",
  md: "w-6 h-6",
  lg: "w-8 h-8",
};

export function Spinner({
  size = "md",
  label,
  className = "",
}: SpinnerProps) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <Loader2
        className={`${sizeMap[size]} animate-spin text-[var(--textSoft)] cursor-wait mx-auto`}
      />
      {label && (
        <span className="text-sm text-[var(--textSoft)] mx-auto">{label}</span>
      )}
    </div>
  );
}
