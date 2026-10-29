import { Navigate, type RouteObject } from "react-router";
import HomePage from "./pages/HomePage.tsx";
import LoginPage from "./pages/login/LoginPage.tsx";
import AccountsPage from "./pages/AccountsPage.tsx";
import AnalyticsPage from "./pages/analytics/AnalyticsPage.tsx";
import LibraryRoot from "./pages/library/LibraryRoot.tsx";
import MediaView from "./pages/library/MediaView.tsx";
import PostsPage from "./pages/PostsPage.tsx";
import PublishMediaPage from "./pages/publish/PublishMediaPage.tsx";
import PublishTextPage from "./pages/publish/PublishTextPage.tsx";
import ProjectLayout from "./pages/ProjectLayout.tsx";
import SettingsPage from "./pages/SettingsPage.tsx";
import AppShell from "./shell/AppShell.tsx";
import AuthGate from "./shell/AuthGate.tsx";
import NotFound, { ProjectNotFound } from "./shell/NotFound.tsx";
import RouteError from "./shell/RouteError.tsx";

export { parseId } from "./route-params.ts";

/**
 * The single route tree (contracts/ui.md §1): createBrowserRouter in the app,
 * createMemoryRouter in tests. The URL is the only source of the project,
 * section and selected media or post.
 */
export const routes: RouteObject[] = [
  // Outside the shell: no navigation and no private data (Feature 020).
  { path: "/login", element: <LoginPage />, errorElement: <RouteError /> },
  {
    path: "/",
    // Nothing below mounts (or requests data) until the session is known.
    element: (
      <AuthGate>
        <AppShell />
      </AuthGate>
    ),
    errorElement: <RouteError />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "settings", element: <SettingsPage /> },
      {
        path: "p/:projectId",
        element: <ProjectLayout />,
        children: [
          { index: true, element: <Navigate to="library" replace /> },
          // A task route: declared before the optional id so it never reads
          // "publish" as a media id.
          {
            path: "library/:mediaId/publish",
            element: <PublishMediaPage />,
            handle: { taskMode: true },
          },
          // The Library root lists entry points; each view below has one route
          // with an optional id, so selecting an item keeps the list mounted
          // (search, filters and polling survive). Static segments outrank
          // `library/:mediaId`, the older detail link (over All media).
          { path: "library", element: <LibraryRoot /> },
          {
            path: "library/unsorted/:mediaId?",
            element: <MediaView kind="unsorted" />,
          },
          { path: "library/all/:mediaId?", element: <MediaView kind="all" /> },
          {
            path: "library/folders/:folderId/:mediaId?",
            element: <MediaView kind="folder" />,
          },
          { path: "library/:mediaId", element: <MediaView kind="all" /> },
          // A task route too, declared before the optional id ("new" is
          // not a post id).
          {
            path: "posts/new",
            element: <PublishTextPage />,
            handle: { taskMode: true },
          },
          { path: "posts/:postId?", element: <PostsPage /> },
          // "new" opens Add account; a number opens that account's detail.
          { path: "accounts/:accountId?", element: <AccountsPage /> },
          { path: "analytics", element: <AnalyticsPage /> },
          { path: "*", element: <ProjectNotFound /> },
        ],
      },
      { path: "*", element: <NotFound /> },
    ],
  },
];
