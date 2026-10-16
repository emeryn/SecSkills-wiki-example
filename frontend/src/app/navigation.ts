import {
  Activity,
  FolderOpen,
  FolderCog,
  LayoutDashboard,
  MessageSquareText,
  ScrollText,
  Settings,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  labelKey: string;
  icon: LucideIcon;
  /** Shown only with this permission (the API enforces it regardless). */
  permission?: string;
}

export interface NavGroup {
  /** Translation key of the group heading; main group has none. */
  labelKey?: string;
  items: NavItem[];
}

/** Sidebar entries (max 7 top-level items). Groups without visible items are not rendered. */
export const NAVIGATION: NavGroup[] = [
  {
    items: [
      { to: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
      { to: "/spaces", labelKey: "nav.spaces", icon: FolderOpen },
      { to: "/ask", labelKey: "nav.ask", icon: MessageSquareText },
    ],
  },
  {
    labelKey: "nav.adminGroup",
    items: [
      {
        to: "/admin",
        labelKey: "nav.overview",
        icon: Activity,
        permission: "dashboard:read",
      },
      { to: "/admin/users", labelKey: "nav.users", icon: Users, permission: "users:read" },
      { to: "/admin/groups", labelKey: "nav.groups", icon: UsersRound, permission: "groups:read" },
      {
        to: "/admin/spaces",
        labelKey: "nav.allSpaces",
        icon: FolderCog,
        permission: "spaces:manage",
      },
      { to: "/admin/audit", labelKey: "nav.audit", icon: ScrollText, permission: "audit:read" },
      {
        to: "/admin/settings/syslog",
        labelKey: "nav.settings",
        icon: Settings,
        permission: "settings:manage",
      },
    ],
  },
];
