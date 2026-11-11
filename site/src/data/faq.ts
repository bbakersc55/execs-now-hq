import { PAYMENTS } from "./pricing";

export const FAQ: { q: string; a: string }[] = [
  {
    q: "Who can see my data?",
    a: "Your practice is sealed: no other practice can see into it, and neither can we as the platform owner. Your team sees what their permission level allows, and each client sees only their own company. The database is backed up every night, and clients sign in with a link sent to their email, so there are no client passwords to leak.",
  },
  {
    q: "What does the AI do on its own?",
    a: "Nothing. Claude drafts: map rows, summaries, follow-ups, meeting proposals. You accept, edit or discard each one. It runs on your own Anthropic key, and the price of each AI action is shown before you click.",
  },
  {
    q: "Can I use it from Claude or ChatGPT?",
    a: "Yes. Connect Claude or ChatGPT to your practice from your own AI account, signed in as yourself. Ask about your clients, tasks and scorecards, or have it draft a digest or an email, which waits in your queue for your approval; notes and tasks it adds are marked as its own. It sees only what you can see, it can't send, delete, sign or move money, every use is in your activity log, and you can disconnect it at any time. Your mail is never shared with it. What you work on there goes to that AI's provider under your own agreement with them.",
  },
  {
    q: "What is a Command Center?",
    a: "A set of tools for one discipline, $50 a month each and $150 at most for all of them: session templates, a KPI list, playbooks, document templates and AI actions. The Operations Command Center is available now; People and Technology are next, then Finance, Sales, Marketing, Projects and Training. Turning one on only offers its pieces. Nothing about a client's scorecard, templates or goals changes, and anything you use is copied into your practice for you to edit.",
  },
  {
    q: "Do you support Outlook?",
    a: "Yes. Connect Google Workspace or Microsoft 365, both available now: sign-in, sending and replies from your own address, your calendar, and meeting notes from Drive or OneDrive.",
  },
  {
    q: "Why does Google warn me when I connect?",
    a: "Google's verification of the app is in progress. Until it's done, Google shows a warning screen when you connect; click through it once and the connection works normally.",
  },
  {
    q: "How do payments work?",
    a: `Invoices carry a pay link from your own merchant account, and the money never passes through us. ${PAYMENTS}`,
  },
  {
    q: "Can I bring my contacts?",
    a: "Yes. Import a CSV and map its columns to fields. Notion and ClickUp import templates are next. HubSpot connects today as a scorecard feed.",
  },
  {
    q: "Does it work on a phone?",
    a: "The whole app works at phone width in the browser, signing included. There's nothing to install.",
  },
  {
    q: "Who counts as a user?",
    a: "Your own team: consultants and assistants. Micro practice includes the owner plus 2, Team the owner plus 20, and further users are $25 a month each. Client companies are unlimited, with up to 25 client users per client included; beyond 25, it's $10 a month for each block of 25.",
  },
  {
    q: "What if I leave?",
    a: "Documents, reports and books download as PDF, Word and spreadsheets whenever you like. A full export of everything is on the list.",
  },
  {
    q: "Is there a trial?",
    a: "No free trial of your own account. Ask for demo access and you get a private copy of the demo practice for 30 days.",
  },
];
