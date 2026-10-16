/** Fictitious, neutral demo data for the README screenshots (example.com, generic names). */

export interface DemoPage {
  title: string;
  body: string;
  children?: DemoPage[];
}

export interface DemoSpace {
  name: string;
  description: string;
  pages: DemoPage[];
}

export const demoUsers = [
  { username: "alice", display_name: "Alice Martin", email: "alice@example.com" },
  { username: "bob", display_name: "Bob Lee", email: "bob@example.com" },
  { username: "chloe", display_name: "Chloe Durand", email: "chloe@example.com" },
  { username: "david", display_name: "David Kim", email: "david@example.com" },
];

const releaseProcess = `Releases ship every second Tuesday. The release manager rotates each cycle and follows the [[Coding guidelines]] for every change.

## Checklist

1. Freeze the \`main\` branch on Monday at 12:00 UTC.
2. Run the full test suite and the security scans.
3. Write the release notes from the merged changes.
4. Tag the release and publish the signed images.
5. Deploy to staging, then to production after sign-off.

## Environments

| Environment | URL | Deployed by |
|---|---|---|
| Staging | https://staging.example.com | CI, on every tag |
| Production | https://app.example.com | Release manager |

## Tagging

\`\`\`bash
git tag -s v2.14.0 -m "Release 2.14.0"
git push origin v2.14.0
\`\`\`

> Never deploy on a Friday. If a fix cannot wait, follow the [[Hotfix checklist]].`;

export const demoSpaces: DemoSpace[] = [
  {
    name: "Engineering",
    description: "Guidelines, architecture and processes of the engineering team",
    pages: [
      {
        title: "Onboarding",
        body: "Welcome to the team! Start with the [[Architecture overview]], then set up your workstation.\n\n## First week\n\n- Get access to the code repository\n- Pair with a teammate on a small fix\n- Read the [[Coding guidelines]]",
      },
      {
        title: "Architecture overview",
        body: "The platform is made of three services behind a reverse proxy.\n\n## Services\n\n- **Web**: single-page application\n- **API**: business logic and authorization\n- **Database**: PostgreSQL with daily encrypted backups",
      },
      {
        title: "Coding guidelines",
        body: "## Principles\n\n- Small, reviewed changes\n- Tests next to the code they cover\n- No secrets in the repository",
      },
      {
        title: "Release process",
        body: releaseProcess,
        children: [
          {
            title: "Hotfix checklist",
            body: "1. Branch from the latest tag.\n2. Fix, test, get one review.\n3. Tag a patch release and deploy.",
          },
          {
            title: "Release notes template",
            body: "## Highlights\n\n## Fixes\n\n## Upgrade notes",
          },
        ],
      },
    ],
  },
  {
    name: "Operations",
    description: "Runbooks and on-call procedures",
    pages: [
      {
        title: "On-call rotation",
        body: "One primary and one secondary engineer, rotating every Monday.",
      },
      {
        title: "Incident response",
        body: "## Severity levels\n\n| Level | Response time |\n|---|---|\n| SEV1 | 15 minutes |\n| SEV2 | 1 hour |\n| SEV3 | Next business day |",
      },
    ],
  },
  {
    name: "Product",
    description: "Roadmap notes, specifications and user research",
    pages: [
      { title: "User research", body: "Interview notes and survey results." },
      { title: "Glossary", body: "Shared vocabulary of the product team." },
    ],
  },
];
