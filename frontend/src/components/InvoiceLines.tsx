import { useEffect, useState } from "react";

import { InvoiceLine } from "../lib/api";
import { dollars, lineAmount, plain, toCents } from "../lib/money";

/** The lines of an invoice or of a recurring invoice: what, how many, at what
 *  price. The amount beside each is worked out here exactly as the server
 *  works it out, so the total on screen is the total that will be billed. */
export function InvoiceLines({ lines, onChange, disabled }: {
  lines: InvoiceLine[]; onChange: (lines: InvoiceLine[]) => void; disabled?: boolean;
}) {
  const set = (index: number, change: Partial<InvoiceLine>) =>
    onChange(lines.map((line, i) => (i === index ? { ...line, ...change } : line)));
  const subtotal = lines.reduce(
    (sum, line) => sum + lineAmount(line.quantity, line.unit_price_cents), 0);
  return (
    <>
      <table className="invoice-lines">
        <thead>
          <tr><th>Description</th><th className="num">Quantity</th>
            <th className="num">Price</th><th className="num">Amount</th><th /></tr>
        </thead>
        <tbody>
          {lines.map((line, index) => (
            <tr key={index}>
              <td>
                <input aria-label={`Description of line ${index + 1}`} value={line.description}
                  disabled={disabled}
                  onChange={(e) => set(index, { description: e.target.value })} />
              </td>
              <td className="num">
                <input aria-label={`Quantity of line ${index + 1}`} value={line.quantity}
                  inputMode="decimal" disabled={disabled} style={{ width: "5.5rem" }}
                  onChange={(e) => set(index, { quantity: e.target.value })} />
              </td>
              <td className="num">
                <PriceBox label={`Price of line ${index + 1}`} cents={line.unit_price_cents}
                  disabled={disabled}
                  onChange={(unit_price_cents) => set(index, { unit_price_cents })} />
              </td>
              <td className="num amount">
                {dollars(lineAmount(line.quantity, line.unit_price_cents))}
              </td>
              <td className="num">
                {!disabled && (
                  <button className="ghost small" aria-label={`Remove line ${index + 1}`}
                    onClick={() => onChange(lines.filter((_, i) => i !== index))}>
                    Remove</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td colSpan={3} className="num">Subtotal</td>
            <td className="num amount">{dollars(subtotal)}</td><td /></tr>
        </tfoot>
      </table>
      {!disabled && (
        <button className="small" onClick={() => onChange([
          ...lines, { description: "", quantity: "1", unit_price_cents: 0 }])}>
          Add a line</button>
      )}
    </>
  );
}

/** A box for dollars that holds cents. What is typed stays as typed until it
 *  reads as an amount, so "45." is not fought with while it becomes "45.50". */
export function PriceBox({ label, cents, onChange, disabled }: {
  label: string; cents: number; onChange: (cents: number) => void; disabled?: boolean;
}) {
  const [text, setText] = useState(cents ? plain(cents) : "");
  // Follows the amount when it changes from outside (a line removed above
  // this one), and otherwise leaves what was typed alone.
  useEffect(() => {
    setText((typed) => ((toCents(typed) ?? 0) === cents ? typed : cents ? plain(cents) : ""));
  }, [cents]);
  return (
    <input aria-label={label} value={text} inputMode="decimal" placeholder="0.00"
      disabled={disabled} style={{ width: "7rem" }}
      onChange={(e) => {
        setText(e.target.value);
        const value = toCents(e.target.value);
        if (value !== null) onChange(value);
        else if (e.target.value.trim() === "") onChange(0);
      }} />
  );
}

/** Lines ready to send: with a description, and a quantity that is a number. */
export function cleanLines(lines: InvoiceLine[]) {
  return lines.filter((line) => line.description.trim()).map((line) => ({
    description: line.description.trim(),
    quantity: toCents(line.quantity) === null ? "1" : line.quantity.trim(),
    unit_price_cents: line.unit_price_cents }));
}
