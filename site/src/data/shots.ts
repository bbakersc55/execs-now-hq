// The product screenshots (public/shots/), captured from a scratch copy of the
// fictional demo practice at 1440x900, 2x. Each card's words are taken from
// what is on that screenshot, so the card and the image agree.
export type Card =
  | { kind: "tag"; label: string; title: string; note?: string; bg?: string; fg?: string }
  | { kind: "comment"; initials: string; author: string; when?: string; text: string }
  | { kind: "signature"; label: string; name: string; note: string }
  | { kind: "figure"; label: string; value: string; note?: string };

export interface Shot {
  alt: string;
  url: string;
  card: Card;
  cardSide?: "left" | "right";
  width?: number;
  height?: number;
  /** The largest file's width, when it isn't twice `width`. */
  fullWidth?: number;
  /** Show only the top of a tall image, this many px (at `width`) high. */
  cropHeight?: number;
}

// The frame's address bar names the screen, not a host: the demo ran on a
// placeholder address, and the frame shouldn't suggest one.
const P = "Summit Operations Partners";

export const SHOTS = {
  "home-dashboard": {
    alt: "The practice owner's Home: tasks due, digests waiting for approval, pipeline moves, open goals, today's calendar and tasks by day.",
    url: `Home · ${P}`,
    card: { kind: "tag", label: "Today", title: "10:00 AM · Weekly check-in", note: "Alder Fasteners" },
  },
  "pipeline-rule": {
    alt: "The Sales pipeline board just after a card moved to Proposal Given, with the stage rule offering to start the follow-up.",
    url: `Pipeline · ${P}`,
    card: { kind: "tag", label: "Stage rule", title: "Start the Proposal Given follow-up?", note: "Gil Navarro · next email in 7 days", bg: "#fdf1e7", fg: "#8a4510" },
  },
  "company-mail": {
    alt: "A client company's Mail tab: every message in and out, newest first, with the client's reply open.",
    url: `Northgate Paper Supply · Mail`,
    card: { kind: "comment", initials: "MH", author: "Martin Hale", when: "reply, filed", text: "Can we roll it to second shift next week?" },
  },
  "strategy-call-tray": {
    alt: "A strategy session during the call, on the Strategy Map section, with Claude's tray holding three proposed map rows to accept or discard.",
    url: `Strategy session · Ironside Fitness`,
    card: { kind: "tag", label: "Drafted by Claude", title: "Keep the trainers you train", note: "60 days · accept, edit or discard", bg: "#eef3fa", fg: "#0d2c54" },
  },
  "strategy-map-pdf": {
    alt: "Page one of a strategy session PDF on the practice's letterhead: headline counts, the mirror, and the six components rated Strong, Watch or Fix.",
    url: `Strategy map · Whitaker Salon Supply.pdf`,
    card: { kind: "tag", label: "The mirror", title: "A schedule built on real capacity", note: "4 fixes on the map, each with an owner", bg: "#eef3fa", fg: "#0d2c54" },
    width: 1440,
    height: 1864,
    fullWidth: 1700,
    cropHeight: 1080,
  },
  "portal-our-work": {
    alt: "The client portal's Our work page in the practice's green and gold: two goals with baseline, current and target, their projects and dated tasks.",
    url: `Our work · Alder Fasteners`,
    card: { kind: "tag", label: "In progress", title: "Ship on time, every time", note: "71% now, target 95%" },
    cardSide: "left",
  },
  "scorecard-tiles": {
    alt: "A client's weekly scorecard as tiles: an on-time delivery gauge, orders shipped, revenue against target, overtime and revenue per order.",
    url: `Scorecard · Northgate Paper Supply`,
    card: { kind: "tag", label: "Behind", title: "On-time delivery 93.7%", note: "This week", bg: "#fdf1e7", fg: "#8a4510" },
  },
  "scorecard-grid": {
    alt: "The same scorecard as a grid: thirteen weeks of readings per KPI, colored on track, behind or off track, with each KPI's owner.",
    url: `Scorecard · Northgate Paper Supply`,
    card: { kind: "tag", label: "Off track", title: "Overtime hours: 50 this week", note: "Target 40 or under", bg: "#fdecec", fg: "#9b1c1c" },
  },
  "my-bonus": {
    alt: "A client team member's My bonus page: $300 earned so far of a $600 monthly bonus, with achievement by component.",
    url: `My bonus · Alder Fasteners`,
    card: { kind: "figure", label: "Earned so far", value: "$300 of $600", note: "22 days left in the month" },
    cardSide: "left",
  },
  "documents-proposal": {
    alt: "The Documents card on a company's page, making a proposal from a template, with its preview on the practice's letterhead.",
    url: `Whitaker Salon Supply · Documents`,
    card: { kind: "tag", label: "Proposal", title: "Grant Whitaker · $4,500 a month", note: "Starts 11/23/2026", bg: "#fdf1e7", fg: "#8a4510" },
  },
  "signing-page": {
    alt: "The signing page the client sees: the proposal, a typed signature, the e-sign consent, and Sign and Decline.",
    url: `Sign · Summit Operations Partners`,
    card: { kind: "signature", label: "Typed signature", name: "Grant Whitaker", note: "ESIGN Act and UETA consent · SHA-256 a53a7222…" },
    cardSide: "left",
  },
  "sending-queue": {
    alt: "The Sending queue: seventeen emails waiting for approval, with an AI-drafted referral touch open in preview.",
    url: `Sending queue · ${P}`,
    card: { kind: "tag", label: "Waiting for you", title: "All 17 waiting for approval", note: "AI-drafted “Checking in” to Hannah Price", bg: "#fdf1e7", fg: "#8a4510" },
  },
  "digest-preview": {
    alt: "A client's weekly progress digest previewed in full before it is sent, grouped by goal, with comments quoted.",
    url: `Digests · ${P}`,
    card: { kind: "tag", label: "Weekly", title: "Weekly update from Summit Operations Partners", note: "Waits for approval until 11/13/2026" },
  },
  "finance-forecast": {
    alt: "Finance, Forecast: cash today, the lowest point in the next 90 days against the practice's floor, a what-if, and the week-by-week cash chart.",
    url: `Forecast · ${P}`,
    card: { kind: "figure", label: "Lowest in 90 days", value: "$40,552.71", note: "Under your floor the week of Dec 7" },
  },
  "invoices-paylink": {
    alt: "An invoice ready to send, with the email it goes out with and its online pay link.",
    url: `Invoices · ${P}`,
    card: { kind: "tag", label: "Pay link", title: "SOP-0199 · $2,750.00", note: "Due November 24, 2026" },
  },
  "settings-branding": {
    alt: "Settings, Branding: the practice's name, colors with contrast checks, and previews of the browser tab, client portal and email.",
    url: `Settings · Branding`,
    card: { kind: "tag", label: "Passes", title: "Contrast 9.48 : 1", note: "Primary #1F4E3D · accent #B98A2E" },
    cardSide: "left",
  },
  "settings-mailboxes": {
    alt: "Settings, Email mailboxes: a client's mailbox, a billing address on Microsoft 365 and a shared info@ address, each with send-as and reply collection.",
    url: `Settings · Email`,
    card: { kind: "tag", label: "Connected", title: "Northgate Paper ops", note: "Send-as checked · replies collected" },
  },
  "bank-connections": {
    alt: "Bank connections: the practice's bank and the household's credit union, connected through Plaid, each account feeding a ledger account.",
    url: `Settings · Bank connections`,
    card: { kind: "tag", label: "Connected", title: "Front Range Bank", note: "Business checking ··4417 · $55,718.80" },
  },
} satisfies Record<string, Shot>;

// VIDEO SLOTS: short silent recordings for sections 03 to 06, to come later.
// Put the MP4 in public/video/ and its path here (e.g. "/video/portal.mp4");
// while empty, the section shows the screenshot, which is also the poster.
export const VIDEO_SLOTS: Record<"03" | "04" | "05" | "06", string> = {
  "03": "",
  "04": "",
  "05": "",
  "06": "",
};
