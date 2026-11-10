export interface Plan {
  name: string;
  price: string;
  per: string;
  summary: string;
  features: string[];
  /** A plain line under the features, set apart. */
  note?: string;
}

const CLIENTS = "Unlimited client companies, up to 25 client users per client included";
const MAIL = "Google Workspace or Microsoft 365, both available now";

export const PLANS: Plan[] = [
  {
    name: "Micro practice",
    price: "$199",
    per: "a month",
    summary: "The practice owner plus 2 more users, consultants or assistants.",
    features: [
      "Each further user $25 a month",
      CLIENTS,
      "Every core module",
      MAIL,
      "Your own Claude key",
      "Your own merchant account, no platform percentage",
      "Five bank connections",
    ],
    note: "Four further users bring Micro practice to $299 a month. At that point Team is the better plan: it includes 20.",
  },
  {
    name: "Team",
    price: "$299",
    per: "a month",
    summary: "The practice owner plus 20 users of any kind.",
    features: [
      "Users 21 and up, $25 a month each",
      "Everything in Micro practice",
      CLIENTS,
      MAIL,
      "Shared clients and referral fees, when they ship",
    ],
  },
  {
    name: "Discipline modules",
    price: "$50",
    per: "a month each",
    summary: "Capped at $150 a month for all of them.",
    features: [
      "Starter templates, analytical tools and SOPs for your discipline",
      "Each priced when it ships",
    ],
  },
];

/** The "Also" block beneath the cards. */
export const ALSO: string[] = [
  "Bank connections beyond the five included: $0.50 a month each.",
  "AI runs on your own key and is charged by your AI provider. Every AI action shows its price before you click.",
  "Client users beyond 25 per client: $10 a month for each block of 25.",
];

/** Payments, said the same way on /pricing and in the FAQ. */
export const PAYMENTS =
  "There is one integrated payment processor today. You apply for your own merchant account through it and are paid into that account, with no platform percentage. If your practice can't be approved, ask us to integrate another mainstream provider.";

export const EVERY_PLAN = [
  "Contacts, companies and two pipelines with stage rules",
  "Strategy sessions with your questions, the map as PDF and Word",
  "Goals, projects and tasks, with progress digests",
  "A meeting queue from your notetaker's notes",
  "The client portal in your brand, sign-in by link",
  "Scorecards with feeds and bonus plans",
  "Proposals, letters and e-signature on your letterhead",
  "Invoices, pay links and autopay into your own merchant account",
  "Books, reconciliation, month close, CPA worksheet, 13-week forecast",
  "Sending queue, email templates and campaigns",
  "Notes and calendar",
  "Google Workspace or Microsoft 365",
  "Works with your AI: connect Claude or ChatGPT; drafts wait for your approval, mail is never shared",
  "Nightly backups",
];
