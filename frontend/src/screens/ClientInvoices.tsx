import { useQuery } from "@tanstack/react-query";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { PortalInvoice, api } from "../lib/api";
import { dollars, longDate } from "../lib/money";

/**
 * A client's own invoices (P4A; matrix 13.4a, the client columns). A client
 * owner and a client team member both see what their company was sent: the
 * number, the dates, the total, what is still owed, and the PDF as it was
 * emailed. Never a draft, and never another company's.
 */
export function ClientInvoices() {
  const rows = useQuery<PortalInvoice[]>({
    queryKey: ["portal-invoices"],
    queryFn: () => api.get<PortalInvoice[]>("/api/portal-invoices/") });
  if (rows.isError) return <Banner kind="bad">{(rows.error as Error).message}</Banner>;
  const list = rows.data ?? [];
  return (
    <>
      <PageHead title="Invoices" sub="The invoices sent to your company, and what is still owed." />
      <Card>
        {!rows.data ? <p>Loading your invoices…</p> : list.length === 0
          ? <Empty>No invoices yet.</Empty> : (
            <table>
              <thead><tr><th>Number</th><th>Issued</th><th>Due</th>
                <th className="money">Total</th><th className="money">Still owed</th>
                <th>Status</th><th /></tr></thead>
              <tbody>
                {list.map((row) => (
                  <tr key={row.id}>
                    <td><strong>{row.number}</strong></td>
                    <td>{longDate(row.issue_date)}</td>
                    <td>{longDate(row.due_date)}</td>
                    <td className="money">{dollars(row.total_cents)}</td>
                    <td className="money">{row.status === "void" ? "" : dollars(row.balance_cents)}</td>
                    <td>
                      <Pill kind={row.status === "paid" ? "ok" : row.status === "void" ? "" : "warn"}>
                        {row.status === "sent" ? "Open" : row.status_label}</Pill>
                      {row.overdue && <> <Pill kind="bad">Due {longDate(row.due_date)}</Pill></>}
                    </td>
                    <td className="money">
                      <a className="btn small" href={`/api/portal-invoices/${row.id}/pdf/`}
                        aria-label={`Download invoice ${row.number}`}>Download</a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </Card>
    </>
  );
}
