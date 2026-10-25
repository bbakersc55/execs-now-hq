import { ReactNode } from "react";

/**
 * The select-all / deselect / act-on-selection strip shared by the Contacts
 * list, the partner table and the Outbox.
 *
 * "Select all" means *all rows currently in view*, not every row in the
 * database — selecting behind a filter you cannot see is how people send
 * things they did not mean to.
 */
export function BulkBar({ total, selected, onSelectAll, onClear, children }: {
  total: number;
  selected: number;
  onSelectAll: () => void;
  onClear: () => void;
  children?: ReactNode;
}) {
  return (
    <div className="row" style={{ alignItems: "center", marginBottom: ".6rem" }}>
      <div style={{ flex: "0 1 auto", minWidth: 0 }}>
        <button className="ghost" onClick={onSelectAll} disabled={total === 0}>
          Select all {total} shown
        </button>{" "}
        {selected > 0 && (
          <button className="ghost" onClick={onClear}>Clear selection</button>
        )}
      </div>
      <div style={{ flex: "1 1 auto" }} className="muted small">
        {selected > 0
          ? `${selected} of ${total} selected`
          : "Tick rows, or select all shown."}
      </div>
      {/* May shrink, so its buttons wrap onto a second line at phone width. */}
      <div style={{ flex: "0 1 auto", minWidth: 0 }}>{children}</div>
    </div>
  );
}
