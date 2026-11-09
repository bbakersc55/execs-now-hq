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
    q: "Do you support Outlook?",
    a: "Yes. Microsoft 365 and Google Workspace are both available now: sign-in, sending and replies from your own address, your calendar, and meeting notes from OneDrive or Drive.",
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
    a: "No. Request demo access and you get a private copy of the demo practice for 30 days, with fictional clients, to try everything.",
  },
];
