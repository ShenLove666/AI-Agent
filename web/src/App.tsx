import { RouterProvider } from "react-router-dom";

import { AuthBootstrap } from "@/components/auth/AuthBootstrap";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { Toast } from "@/components/common/Toast";
import { router } from "@/router";

export default function App() {
  return (
    <ErrorBoundary>
      <AuthBootstrap>
        <RouterProvider router={router} />
      </AuthBootstrap>
      <Toast />
    </ErrorBoundary>
  );
}
