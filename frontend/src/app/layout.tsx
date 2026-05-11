import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { LayoutShell } from "@/components/layout/LayoutShell";
import { QueryProvider } from "@/providers/QueryProvider";
import { WebSocketProvider } from "@/providers/WebSocketProvider";
import { Toaster } from "sonner";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ProvenQuant Trader",
  description: "Paper trading bot management",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <QueryProvider>
          <WebSocketProvider>
            <LayoutShell>{children}</LayoutShell>
            <Toaster richColors position="top-right" />
          </WebSocketProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
