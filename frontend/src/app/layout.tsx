import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";
import { WebSocketStatus } from "@/components/layout/WebSocketStatus";
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
            <div className="flex h-screen overflow-hidden">
              <Sidebar />
              <div className="flex flex-1 flex-col overflow-hidden">
                <header className="flex h-12 items-center justify-end border-b px-4">
                  <WebSocketStatus />
                </header>
                <main className="flex-1 overflow-auto p-6">{children}</main>
              </div>
            </div>
            <Toaster richColors position="top-right" />
          </WebSocketProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
