/** A feed's "Also read the current period as it goes" (Sheet, Track, HubSpot
 *  and app feeds alike). On by default for a Last or Average roll-up, off
 *  for a Sum, whose part-period total would read as a shortfall. */
export function ReadOpenChoice({ id, checked, byDefault, onChange }: {
  id: string; checked: boolean; byDefault: boolean; onChange: (on: boolean) => void;
}) {
  return (
    <div className="sc-read-open">
      <label className="sc-check" htmlFor={id}>
        <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        {" "}Also read the current period as it goes</label>
      <p className="small muted" style={{ margin: 0 }}>The open period shows a reading marked “so far”, replaced
        at each refresh; when the period closes, the last value read is its reading. A number typed by hand
        still wins. {byDefault ? "On by default for this roll-up." : "Off by default for a sum."}</p>
    </div>
  );
}

/** The choice as the form holds it: what the person ticked, else the
 *  feed's saved one, else the KPI's default. */
export function readOpenValue(ticked: boolean | null, saved: boolean | undefined,
  byDefault: boolean | undefined): boolean {
  return ticked ?? saved ?? byDefault ?? false;
}
