import type { RouteObject } from "react-router";
import { AccountPage } from "../features/account/pages/AccountPage";
import { SetupPasswordPage } from "../features/account/pages/SetupPasswordPage";
import { SetupSecurityPage } from "../features/account/pages/SetupSecurityPage";
import { AdminDashboardPage } from "../features/admin/pages/AdminDashboardPage";
import { AuditPage } from "../features/admin/pages/AuditPage";
import { GroupDetailPage } from "../features/admin/pages/GroupDetailPage";
import { GroupsPage } from "../features/admin/pages/GroupsPage";
import { UserDetailPage } from "../features/admin/pages/UserDetailPage";
import { SettingsPage } from "../features/admin/pages/SettingsPage";
import { SpacesAdminPage } from "../features/admin/pages/SpacesAdminPage";
import { UsersPage } from "../features/admin/pages/UsersPage";
import { ForgotPasswordPage } from "../features/auth/pages/ForgotPasswordPage";
import { LoginPage } from "../features/auth/pages/LoginPage";
import { ResetPasswordPage } from "../features/auth/pages/ResetPasswordPage";
import { VerifyPage } from "../features/auth/pages/VerifyPage";
import { AskPage } from "../features/ask/pages/AskPage";
import { DashboardPage } from "../features/dashboard/pages/DashboardPage";
import { HelpPage } from "../features/help/pages/HelpPage";
import { SearchPage } from "../features/search/pages/SearchPage";
import { PageEditPage } from "../features/spaces/pages/PageEditPage";
import { PageHistoryPage } from "../features/spaces/pages/PageHistoryPage";
import { PageViewPage } from "../features/spaces/pages/PageViewPage";
import { SpaceIndexPage } from "../features/spaces/pages/SpaceIndexPage";
import { SpaceLayout } from "../features/spaces/pages/SpaceLayout";
import { SpaceSettingsPage } from "../features/spaces/pages/SpaceSettingsPage";
import { SpacesPage } from "../features/spaces/pages/SpacesPage";
import { TrashPage } from "../features/spaces/pages/TrashPage";
import { AppShell } from "./AppShell";
import { NotFoundPage } from "./NotFoundPage";
import { RequireAuth, RequirePermission } from "./RequireAuth";
import { RouteError } from "./RouteError";

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage />, errorElement: <RouteError /> },
  { path: "/login/verify", element: <VerifyPage />, errorElement: <RouteError /> },
  { path: "/forgot-password", element: <ForgotPasswordPage />, errorElement: <RouteError /> },
  { path: "/reset-password", element: <ResetPasswordPage />, errorElement: <RouteError /> },
  { path: "/setup/password", element: <SetupPasswordPage />, errorElement: <RouteError /> },
  { path: "/setup/security", element: <SetupSecurityPage />, errorElement: <RouteError /> },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    errorElement: <RouteError />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "account", element: <AccountPage /> },
      { path: "search", element: <SearchPage /> },
      { path: "ask", element: <AskPage /> },
      { path: "help", element: <HelpPage /> },
      { path: "help/:audience/:topic", element: <HelpPage /> },
      { path: "spaces", element: <SpacesPage /> },
      {
        path: "spaces/:space",
        element: <SpaceLayout />,
        children: [
          { index: true, element: <SpaceIndexPage /> },
          { path: "new", element: <PageEditPage mode="create" /> },
          { path: "pages/:slug", element: <PageViewPage /> },
          { path: "pages/:slug/edit", element: <PageEditPage mode="edit" /> },
          { path: "pages/:slug/history", element: <PageHistoryPage /> },
          { path: "trash", element: <TrashPage /> },
          { path: "settings", element: <SpaceSettingsPage /> },
        ],
      },
      {
        path: "admin",
        element: (
          <RequirePermission permission="dashboard:read">
            <AdminDashboardPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/audit",
        element: (
          <RequirePermission permission="audit:read">
            <AuditPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/settings/:section?",
        element: (
          <RequirePermission permission="settings:manage">
            <SettingsPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/users",
        element: (
          <RequirePermission permission="users:read">
            <UsersPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/users/:userId",
        element: (
          <RequirePermission permission="users:read">
            <UserDetailPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/groups",
        element: (
          <RequirePermission permission="groups:read">
            <GroupsPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/groups/:groupId",
        element: (
          <RequirePermission permission="groups:read">
            <GroupDetailPage />
          </RequirePermission>
        ),
      },
      {
        path: "admin/spaces",
        element: (
          <RequirePermission permission="spaces:manage">
            <SpacesAdminPage />
          </RequirePermission>
        ),
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
