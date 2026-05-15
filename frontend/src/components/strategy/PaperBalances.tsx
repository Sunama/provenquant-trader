interface Props {
  balances: Record<string, number>;
}

export function PaperBalances({ balances }: Props) {
  if (Object.keys(balances).length === 0) return null;
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-xs font-semibold text-muted-foreground mb-3 uppercase tracking-wide">Paper Balances</p>
      <div className="flex flex-wrap gap-4">
        {Object.entries(balances).map(([asset, qty]) => (
          <div key={asset} className="flex flex-col">
            <span className="text-xs text-muted-foreground">{asset}</span>
            <span className="text-base font-mono font-semibold">
              {qty.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
