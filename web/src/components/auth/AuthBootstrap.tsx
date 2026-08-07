import { useEffect } from "react";

import { useAuthStore } from "@/stores/authStore";

interface AuthBootstrapProps {
  children: React.ReactNode;
}

export function AuthBootstrap({ children }: AuthBootstrapProps) {
  const checkAuth = useAuthStore((state) => state.checkAuth);
  const isInitialized = useAuthStore((state) => state.isInitialized);

  useEffect(() => {
    if (!isInitialized) void checkAuth().catch(() => null);
  }, [checkAuth, isInitialized]);

  if (!isInitialized) {
    return (
      <div role="status" aria-live="polite">
        正在连接运营台
      </div>
    );
  }

  return <>{children}</>;
}
