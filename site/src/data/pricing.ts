export interface Plan {
  name: string;
  price: string;
  per: string;
  summary: string;
  features: string[];
}

export const PLANS: Plan[] = [
  {
    name: "Micro practice",
    price: "$200",
    per: "a month",
    summary: "The practice owner plus one assistant.",
    features: [
      "Unlimited clients and client users",
      "Every core module",
      "Gmail or Microsoft 365",
      "Your own Claude key",
      "Your own payment processor, no platform percentage",
      "Five bank connections",
    ],
  },
  {
    name: "Team",
    price: "$299",
    per: "a month",
    summary: "Everything in Micro practice, plus associates.",
    features: [
      "Associates",
      "Five practice seats included",
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

export const PRICING_FOOTNOTE =
  "Bank connections beyond five are $0.50 a month each. Client seats are never charged. AI runs on your own key and shows its price before each click.";

export const EVERY_PLAN = [
  "Contacts, companies and two pipelines with stage rules",
  "Strategy sessions with your questions, the map as PDF and Word",
  "Goals, projects and tasks, with progress digests",
  "The client portal in your brand, sign-in by link",
  "Scorecards with feeds and bonus plans",
  "Proposals, letters and e-signature on your letterhead",
  "Invoices, pay links and autopay through your processor",
  "Books, reconciliation, month close, CPA worksheet, 13-week forecast",
  "Sending queue, email templates and campaigns",
  "Notes, meeting queue from your notetaker, calendar",
  "Nightly backups",
];
