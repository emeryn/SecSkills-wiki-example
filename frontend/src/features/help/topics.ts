/**
 * Embedded help, bundled at build time from `docs/help/<audience>/<topic>.md` (no runtime fetch).
 * The first `# Heading` of each file is its title; `order` in the file name prefix sorts topics.
 */

export type Audience = "user" | "admin";

export interface HelpTopic {
  audience: Audience;
  slug: string;
  title: string;
  source: string;
}

const files = import.meta.glob<string>("../../../../docs/help/*/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

const AUDIENCES: readonly Audience[] = ["user", "admin"];

/** `.../docs/help/<audience>/<NN->slug.md` → audience and slug. */
function parsePath(path: string): { audience: Audience; slug: string } | null {
  const [folder = "", file = ""] = path.split("/").slice(-2);
  const audience = AUDIENCES.find((candidate) => candidate === folder);
  if (audience === undefined || !file.endsWith(".md")) return null;
  return { audience, slug: file.slice(0, -3).replace(/^\d+-/, "") };
}

export const HELP_TOPICS: HelpTopic[] = Object.entries(files)
  .sort(([a], [b]) => a.localeCompare(b))
  .flatMap(([path, source]) => {
    const parsed = parsePath(path);
    if (parsed === null) return [];
    const { audience, slug } = parsed;
    const title = /^#\s+(.+)$/m.exec(source)?.[1]?.trim() ?? slug;
    return [{ audience, slug, title, source }];
  });

export function findTopic(audience: string | undefined, slug: string | undefined) {
  return HELP_TOPICS.find((topic) => topic.audience === audience && topic.slug === slug);
}

/** Help topic for the current page, most specific route first. */
const ROUTES: [RegExp, string][] = [
  [/^\/admin\/settings/, "admin/settings"],
  [/^\/admin\/audit/, "admin/audit"],
  [/^\/admin\/users/, "admin/users-and-groups"],
  [/^\/admin\/groups/, "admin/users-and-groups"],
  [/^\/admin\/spaces/, "admin/spaces"],
  [/^\/admin\/?$/, "admin/dashboard"],
  [/^\/spaces\/[^/]+\/pages\/[^/]+\/edit$/, "user/editing"],
  [/^\/spaces\/[^/]+\/new$/, "user/editing"],
  [/^\/spaces\/[^/]+\/pages\/[^/]+\/history$/, "user/history"],
  [/^\/spaces\/[^/]+\/trash$/, "user/history"],
  [/^\/spaces\/[^/]+\/settings$/, "user/spaces"],
  [/^\/spaces/, "user/spaces"],
  [/^\/search/, "user/search"],
  [/^\/ask/, "user/ask"],
  [/^\/account/, "user/account"],
];

export function helpPathFor(pathname: string, canAdminister: boolean): string {
  const found = ROUTES.find(([pattern]) => pattern.test(pathname))?.[1] ?? "user/getting-started";
  if (found.startsWith("admin/") && !canAdminister) return "/help/user/getting-started";
  return `/help/${found}`;
}
