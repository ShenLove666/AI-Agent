import * as React from "react";

import { Header } from "@/components/layout/Header";
import { Sidebar } from "@/components/layout/Sidebar";

interface MainLayoutProps {
  children: React.ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = React.useState(false);

  return (
    <div className="flex h-[100dvh] min-h-0 overflow-hidden bg-[var(--merchant-surface-subtle)]">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Header onToggleSidebar={() => setSidebarOpen((prev) => !prev)} />
        <main className="min-h-0 flex-1 overflow-hidden bg-[var(--merchant-surface)]">
          {children}
        </main>
      </div>
    </div>
  );
}
