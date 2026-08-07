import { lazy, Suspense } from "react";
import { Navigate, createBrowserRouter } from "react-router-dom";

import { useAuthStore } from "@/stores/authStore";

const LoginPage = lazy(() => import("@/pages/LoginPage").then((module) => ({ default: module.LoginPage })));
const ChatPage = lazy(() => import("@/pages/ChatPage").then((module) => ({ default: module.ChatPage })));
const ChangeLogsPage = lazy(() =>
  import("@/pages/ChangeLogsPage").then((module) => ({ default: module.ChangeLogsPage }))
);
const DocPreviewPage = lazy(() =>
  import("@/pages/DocPreviewPage").then((module) => ({ default: module.DocPreviewPage }))
);
const NotFoundPage = lazy(() =>
  import("@/pages/NotFoundPage").then((module) => ({ default: module.NotFoundPage }))
);
const AdminLayout = lazy(() =>
  import("@/pages/admin/AdminLayout").then((module) => ({ default: module.AdminLayout }))
);
const DashboardPage = lazy(() =>
  import("@/pages/admin/dashboard/DashboardPage").then((module) => ({ default: module.DashboardPage }))
);
const OperationsPage = lazy(() =>
  import("@/pages/admin/operations/OperationsPage").then((module) => ({ default: module.OperationsPage }))
);
const RetailOperationsPage = lazy(() =>
  import("@/pages/admin/retail/RetailOperationsPage").then((module) => ({ default: module.RetailOperationsPage }))
);
const KnowledgeListPage = lazy(() =>
  import("@/pages/admin/knowledge/KnowledgeListPage").then((module) => ({ default: module.KnowledgeListPage }))
);
const KnowledgeDocumentsPage = lazy(() =>
  import("@/pages/admin/knowledge/KnowledgeDocumentsPage").then((module) => ({
    default: module.KnowledgeDocumentsPage
  }))
);
const KnowledgeChunksPage = lazy(() =>
  import("@/pages/admin/knowledge/KnowledgeChunksPage").then((module) => ({ default: module.KnowledgeChunksPage }))
);
const RagTracePage = lazy(() =>
  import("@/pages/admin/traces/RagTracePage").then((module) => ({ default: module.RagTracePage }))
);
const RagTraceDetailPage = lazy(() =>
  import("@/pages/admin/traces/RagTraceDetailPage").then((module) => ({ default: module.RagTraceDetailPage }))
);
const SystemSettingsPage = lazy(() =>
  import("@/pages/admin/settings/SystemSettingsPage").then((module) => ({ default: module.SystemSettingsPage }))
);
const UserListPage = lazy(() =>
  import("@/pages/admin/users/UserListPage").then((module) => ({ default: module.UserListPage }))
);

function PageFallback() {
  return <div role="status">正在加载页面</div>;
}

function withPageSuspense(children: JSX.Element) {
  return <Suspense fallback={<PageFallback />}>{children}</Suspense>;
}

function RequireAuth({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitialized = useAuthStore((state) => state.isInitialized);
  if (!isInitialized) return <PageFallback />;
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitialized = useAuthStore((state) => state.isInitialized);

  if (!isInitialized) return <PageFallback />;
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (user?.role !== "admin") {
    return <Navigate to="/chat" replace />;
  }

  return children;
}

function RedirectIfAuth({ children }: { children: JSX.Element }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitialized = useAuthStore((state) => state.isInitialized);
  const user = useAuthStore((state) => state.user);
  if (!isInitialized) return <PageFallback />;
  if (isAuthenticated) {
    return <Navigate to={user?.role === "admin" ? "/admin/retail" : "/chat"} replace />;
  }
  return children;
}

function HomeRedirect() {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isInitialized = useAuthStore((state) => state.isInitialized);
  const user = useAuthStore((state) => state.user);
  if (!isInitialized) return <PageFallback />;
  return <Navigate to={isAuthenticated ? (user?.role === "admin" ? "/admin/retail" : "/chat") : "/login"} replace />;
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <HomeRedirect />
  },
  {
    path: "/login",
    element: (
      <RedirectIfAuth>
        {withPageSuspense(<LoginPage />)}
      </RedirectIfAuth>
    )
  },
  {
    path: "/chat",
    element: (
      <RequireAuth>
        {withPageSuspense(<ChatPage />)}
      </RequireAuth>
    )
  },
  {
    path: "/chat/:sessionId",
    element: (
      <RequireAuth>
        {withPageSuspense(<ChatPage />)}
      </RequireAuth>
    )
  },
  {
    path: "/change-logs",
    element: (
      <RequireAuth>
        {withPageSuspense(<ChangeLogsPage />)}
      </RequireAuth>
    )
  },
  {
    path: "/preview/doc/:docId",
    element: (
      <RequireAuth>
        {withPageSuspense(<DocPreviewPage />)}
      </RequireAuth>
    )
  },
  {
    path: "/admin",
    element: (
      <RequireAdmin>
        {withPageSuspense(<AdminLayout />)}
      </RequireAdmin>
    ),
    children: [
      {
        index: true,
        element: <Navigate to="/admin/retail" replace />
      },
      {
        path: "retail",
        element: withPageSuspense(<RetailOperationsPage />)
      },
      {
        path: "dashboard",
        element: withPageSuspense(<DashboardPage />)
      },
      {
        path: "operations",
        element: withPageSuspense(<OperationsPage />)
      },
      {
        path: "knowledge",
        element: withPageSuspense(<KnowledgeListPage />)
      },
      {
        path: "knowledge/:kbId",
        element: withPageSuspense(<KnowledgeDocumentsPage />)
      },
      {
        path: "knowledge/:kbId/docs/:docId",
        element: withPageSuspense(<KnowledgeChunksPage />)
      },
      {
        path: "traces",
        element: withPageSuspense(<RagTracePage />)
      },
      {
        path: "traces/:traceId",
        element: withPageSuspense(<RagTraceDetailPage />)
      },
      {
        path: "settings",
        element: withPageSuspense(<SystemSettingsPage />)
      },
      {
        path: "users",
        element: withPageSuspense(<UserListPage />)
      },
      {
        path: "*",
        element: withPageSuspense(<NotFoundPage />)
      }
    ]
  },
  {
    path: "*",
    element: withPageSuspense(<NotFoundPage />)
  }
]);
