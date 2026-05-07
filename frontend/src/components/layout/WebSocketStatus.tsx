"use client";

import { useWsConnection } from "@/providers/WebSocketProvider";
import { cn } from "@/lib/utils";

export function WebSocketStatus() {
  const { connected } = useWsConnection();

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span
        className={cn(
          "h-2 w-2 rounded-full",
          connected ? "bg-green-500 animate-pulse" : "bg-red-400"
        )}
      />
      {connected ? "Live" : "Connecting..."}
    </div>
  );
}
