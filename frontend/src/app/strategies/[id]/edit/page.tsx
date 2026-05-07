"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { strategies } from "@/lib/api";
import { StrategyEditor } from "@/components/editor/StrategyEditor";

export default function EditStrategyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const { data, isLoading } = useQuery({
    queryKey: ["strategy", id],
    queryFn: () => strategies.get(id),
  });

  if (isLoading) return <p className="text-muted-foreground">Loading…</p>;
  if (!data) return <p className="text-muted-foreground">Strategy not found.</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Edit Strategy: {id}</h1>
      <StrategyEditor initial={data} />
    </div>
  );
}
