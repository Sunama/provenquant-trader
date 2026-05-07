import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string;
  subtext?: string;
  positive?: boolean;
  negative?: boolean;
}

export function StatCard({ label, value, subtext, positive, negative }: StatCardProps) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p
        className={cn(
          "mt-1 text-2xl font-bold",
          positive && "text-green-600",
          negative && "text-red-500"
        )}
      >
        {value}
      </p>
      {subtext && <p className="mt-1 text-xs text-muted-foreground">{subtext}</p>}
    </div>
  );
}
