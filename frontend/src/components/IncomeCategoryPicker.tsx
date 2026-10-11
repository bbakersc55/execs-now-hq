import { useQuery } from "@tanstack/react-query";

import { FinanceCategory, FinanceSettingsData, api } from "../lib/api";
import { categoryOptions } from "../lib/finance";

/**
 * Where an invoice's payments are entered in the books (owner, 2026-10-10).
 * A recurring invoice goes to one income category and any other invoice to
 * another, both chosen in the finance settings; this lets one invoice, or
 * one schedule, name a different one.
 *
 * The practice owner's only: the chart is theirs alone, so the server sends
 * `income_category` to nobody else and this is drawn for nobody else.
 */
export function IncomeCategoryPicker({ kind, value, onChange, disabled, label }: {
  kind: "recurring" | "one_off"; value: string; onChange: (id: string) => void;
  disabled?: boolean; label: string;
}) {
  const categories = useQuery<FinanceCategory[]>({
    queryKey: ["finance-categories"],
    queryFn: () => api.get<FinanceCategory[]>("/api/finance-categories/") });
  const settings = useQuery<FinanceSettingsData>({
    queryKey: ["finance-settings"],
    queryFn: () => api.get<FinanceSettingsData>("/api/finance-settings/") });
  const all = categories.data ?? [];
  const income = all.filter((c) => c.type === "income" && (!c.archived || c.id === value));
  const usual = settings.data
    ? (kind === "recurring" ? settings.data.recurring_income_category
      : settings.data.one_off_income_category) || settings.data.invoice_income_category
    : "";
  const usualName = all.find((c) => c.id === usual)?.name;
  return (
    <select aria-label={label} value={value} disabled={disabled}
      onChange={(e) => onChange(e.target.value)}>
      <option value="">
        {kind === "recurring" ? "As recurring invoices usually are" : "As invoices usually are"}
        {usualName ? ` (${usualName})` : ""}</option>
      {categoryOptions(income, all).map(([id, name]) => (
        <option key={id} value={id}>{name}</option>))}
    </select>
  );
}
