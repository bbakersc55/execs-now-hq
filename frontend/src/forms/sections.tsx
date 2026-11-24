/** The "New owner and property" sections. The owner's link and the review
 *  screen in the app both draw them; `ctx.api` decides where a change goes. */
import { useState, type ReactElement, type ReactNode } from "react";
import {
  bathSummary, bathType, bedLabel, label, labels, roomSummary, totalSleeps,
} from "./derive";
import type {
  About, Access, Answers, Bed, Ctx, ExtraOwner, Home, Option, OwnerForm, Place, Property,
} from "./types";
import {
  Area, Checks, Choice, Field, Note, Ranges, SecretField, Select, Stepper, Text, YesNo,
} from "./ui";

const opts = (form: OwnerForm, name: string): Option[] => form.options[name] ?? [];

/** A closet or alarm answered "yes" before the question said how it opens. */
const withCode = (value: string | undefined) => (value === "yes" ? "code" : value);

/** The codes the answers call for, by slot, as the server works them out
 *  (apps/intake/derive.py, code_slots). */
export function codeSlots(a: Access): string[] {
  const out: string[] = [];
  if (a.door === "smart_lock" || a.door === "keypad" || a.door === "lockbox") out.push("door");
  if (withCode(a.owner_closet) === "code") out.push("owner_closet");
  if (withCode(a.alarm) === "code") out.push("alarm");
  (a.extra_codes ?? []).forEach((x, i) => { if (x.type > 0) out.push(`extra-${i}`); });
  return out;
}

/** The review screen only: beside a sensitive value the send needs and
 *  doesn't have, the two ways out (owner, 2026-11-20): enter it here, or
 *  mark that there is none. Nothing on the owner's form. */
function Needed({ ctx, name, label }: { ctx: Ctx; name: string; label: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const state = ctx.needs?.[name];
  if (ctx.mode !== "staff" || !ctx.markNone || (state !== "missing" && state !== "none"))
    return null;
  const mark = async (none: boolean) => {
    setBusy(true);
    setError("");
    try { await ctx.markNone!(name, none); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  // "door code", "business Tax ID", "Wi-Fi password": as in a sentence.
  const what = name.startsWith("code:") ? label.toLowerCase()
    : name === "tax_id" ? "business Tax ID" : label;
  return (
    <div className={`ix-needed${state === "none" ? " ix-none" : ""}`} data-needed={name}>
      {state === "missing" ? (
        <>
          <span><strong>Needed before Send:</strong> the {what} isn't in ENHQ. Enter it above,
            or</span>
          <button type="button" className="ix-link" disabled={busy}
            onClick={() => void mark(true)}>mark that there is none</button>
        </>
      ) : (
        <>
          <span>Marked as having no {what}: nothing is sent for it.</span>
          <button type="button" className="ix-link" disabled={busy}
            onClick={() => void mark(false)}>Undo</button>
        </>
      )}
      {error && <span className="ix-error" role="alert">{error}</span>}
    </div>
  );
}

function Block({ title, summary, children, onRemove, removeLabel }: {
  title: string; summary?: string; children: ReactNode; onRemove?: () => void;
  removeLabel?: string;
}) {
  return (
    <section className="ix-block" aria-label={title}>
      <header className="ix-block-head">
        <h3>{title}</h3>
        {onRemove && <button type="button" className="ix-link ix-remove"
          onClick={onRemove}>{removeLabel ?? "Remove"}</button>}
      </header>
      {summary && <p className="ix-summary">{summary}</p>}
      {children}
    </section>
  );
}

function GenericFields({ ctx, section }: { ctx: Ctx; section: string }) {
  const fields = ctx.form.custom_fields.filter((f) => f.section === section);
  if (!fields.length) return null;
  const values = ctx.answers.custom ?? {};
  const set = (ref: string, v: string | string[]) =>
    ctx.update("custom", { ...values, [ref]: v });
  return (
    <>
      {fields.map((f) => {
        const value = values[f.reference];
        if (f.type === "select")
          return <Select key={f.reference} label={f.label} hint={f.help} options={f.options}
            value={typeof value === "string" ? value : ""} onChange={(v) => set(f.reference, v)} />;
        if (f.type === "multiselect")
          return <Checks key={f.reference} label={f.label} hint={f.help} options={f.options}
            values={Array.isArray(value) ? value : []} onChange={(v) => set(f.reference, v)} />;
        if (f.type === "text")
          return <Area key={f.reference} label={f.label} hint={f.help}
            value={typeof value === "string" ? value : ""} onChange={(v) => set(f.reference, v)} />;
        return <Text key={f.reference} label={f.label} hint={f.help}
          type={f.type === "date" ? "date" : "text"}
          value={typeof value === "string" ? value : ""} onChange={(v) => set(f.reference, v)} />;
      })}
    </>
  );
}

// ------------------------------------------------------------ about you

export function AboutSection({ ctx }: { ctx: Ctx }) {
  const a: About = ctx.answers.about ?? {};
  const set = (patch: Partial<About>) => ctx.update("about", { ...a, ...patch });
  const extras = a.extra_owners ?? [];
  const setExtra = (i: number, patch: Partial<ExtraOwner>) =>
    set({ extra_owners: extras.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  const you = ctx.mode === "owner";
  return (
    <>
      <div className="ix-two">
        <Text label="First name" value={a.first_name} autoComplete="given-name"
          onChange={(v) => set({ first_name: v })} />
        <Text label="Last name" value={a.last_name} autoComplete="family-name"
          onChange={(v) => set({ last_name: v })} />
      </div>
      <Text label="Name on the account" value={a.account_name}
        hint={you ? "If you own the home through a company or trust, its name. Otherwise, your "
          + "own name." : "The company or trust, or the owner's own name."}
        onChange={(v) => set({ account_name: v })} />
      <Field label="Mailing address"
        hint={you ? "Where we send mail, not the property. We'll ask about the property next."
          : "Not the property's address."}>
        <div className="ix-stack">
          <Text label="Street" value={a.street} autoComplete="address-line1"
            onChange={(v) => set({ street: v })} />
          <Text label="Apartment, suite or unit (optional)" value={a.street2}
            autoComplete="address-line2" onChange={(v) => set({ street2: v })} />
          <div className="ix-three">
            <Text label="City" value={a.city} autoComplete="address-level2"
              onChange={(v) => set({ city: v })} />
            <Text label="State" value={a.state} autoComplete="address-level1"
              onChange={(v) => set({ state: v })} />
            <Text label="ZIP code" value={a.postal} autoComplete="postal-code" inputMode="numeric"
              onChange={(v) => set({ postal: v })} />
          </div>
        </div>
      </Field>
      <div className="ix-two">
        <Text label="Mobile phone" value={a.mobile} type="tel" inputMode="tel"
          autoComplete="tel" onChange={(v) => set({ mobile: v })} />
        <Text label="Email" value={a.email} type="email" inputMode="email" autoComplete="email"
          onChange={(v) => set({ email: v })} />
      </div>
      <Choice label={you ? "How do you like us to reach you?" : "Preferred contact"}
        options={opts(ctx.form, "contact_pref")} value={a.contact_pref} columns={3}
        onChange={(v) => set({ contact_pref: v })} />
      <Select label={`How did ${you ? "you" : "they"} hear about ${ctx.brand}?`}
        options={opts(ctx.form, "heard")} value={a.heard}
        onChange={(v) => set({ heard: v })} />
      {(a.heard === "referral" || a.heard === "other" || a.heard === "owner") && (
        <Text label={a.heard === "other" ? "Tell us a little more" : "Who referred you?"}
          value={a.heard_detail} onChange={(v) => set({ heard_detail: v })} />
      )}
      <Block title="Emergency contact">
        <p className="ix-hint">Someone we could contact in an emergency, other than
          {you ? " you" : " the owner"}.</p>
        <Text label="Name" value={a.emergency?.name}
          onChange={(v) => set({ emergency: { ...a.emergency, name: v } })} />
        <Text label="Phone" type="tel" inputMode="tel" value={a.emergency?.phone}
          onChange={(v) => set({ emergency: { ...a.emergency, phone: v } })} />
        <Text label="Address (optional)" value={a.emergency?.address}
          onChange={(v) => set({ emergency: { ...a.emergency, address: v } })} />
      </Block>
      <YesNo label="Are there any other owners?" value={a.has_extra_owners}
        onChange={(v) => set({
          has_extra_owners: v,
          extra_owners: v === "yes" && !extras.length
            ? [{ first_name: "", last_name: "", email: "", mobile: "", portal: false }] : extras,
        })} />
      {a.has_extra_owners === "yes" && (
        <>
          {extras.map((x, i) => (
            <Block key={i} title={`Other owner ${i + 1}`}
              onRemove={() => set({ extra_owners: extras.filter((_, j) => j !== i) })}>
              <div className="ix-two">
                <Text label="First name" value={x.first_name}
                  onChange={(v) => setExtra(i, { first_name: v })} />
                <Text label="Last name" value={x.last_name}
                  onChange={(v) => setExtra(i, { last_name: v })} />
              </div>
              <div className="ix-two">
                <Text label="Email" type="email" inputMode="email" value={x.email}
                  onChange={(v) => setExtra(i, { email: v })}
                  error={!x.email && !x.mobile && (x.first_name || x.last_name)
                    ? "Add an email or a mobile number." : undefined} />
                <Text label="Mobile phone" type="tel" inputMode="tel" value={x.mobile}
                  onChange={(v) => setExtra(i, { mobile: v })} />
              </div>
              <label className={`ix-card ix-check ix-wide${x.portal ? " ix-on" : ""}`}>
                <input type="checkbox" checked={x.portal}
                  onChange={() => setExtra(i, { portal: !x.portal })} />
                <span>Give them their own login to the owner portal</span>
              </label>
            </Block>
          ))}
          <button type="button" className="ix-btn ix-btn-ghost" onClick={() => set({
            extra_owners: [...extras, { first_name: "", last_name: "", email: "", mobile: "",
                                        portal: false }],
          })}>+ Add another owner</button>
        </>
      )}
      <GenericFields ctx={ctx} section="about" />
    </>
  );
}

// ------------------------------------------------------------ tax

export function TaxSection({ ctx }: { ctx: Ctx }) {
  const kind = ctx.answers.tax?.kind;
  const you = ctx.mode === "owner";
  return (
    <>
      <Choice label={you ? "For tax reporting, will you use a business Tax ID or your Social "
        + "Security number?" : "Tax ID or Social Security number"}
        options={opts(ctx.form, "tax_kind")} value={kind}
        onChange={(v) => ctx.update("tax", { kind: v })} />
      {kind === "tax_id" && (
        <>
          <SecretField label="Business Tax ID (EIN)" inputMode="numeric" name="tax_id"
            hint="9 digits, like 12-3456789. Please don't enter a Social Security number here."
            saved={!!ctx.secrets.tax_id} last4={ctx.secrets.tax_id?.last4}
            onSave={async (v) => ctx.setSecrets(await ctx.api.putSecret("tax_id", "", v))}
            onClear={async () => ctx.setSecrets(await ctx.api.clearSecret("tax_id", ""))} />
          <Needed ctx={ctx} name="tax_id" label="Business Tax ID" />
        </>
      )}
      {kind === "ssn" && (
        <Note tone="safe">You'll add your Social Security number yourself, in your owner portal,
          later. This form never asks for it.</Note>
      )}
      <Note tone="safe">Bank details for your payouts are added the same way, by you, in your
        owner portal. This form never asks for them.</Note>
    </>
  );
}

// ------------------------------------------------------------ the property

export function PropertySection({ ctx }: { ctx: Ctx }) {
  const p: Property = ctx.answers.property ?? {};
  const set = (patch: Partial<Property>) => ctx.update("property", { ...p, ...patch });
  return (
    <>
      <Text label="Street address" value={p.street} autoComplete="off"
        onChange={(v) => set({ street: v })} />
      <Text label="Unit or building (optional)" value={p.street2}
        onChange={(v) => set({ street2: v })} />
      <div className="ix-three">
        <Text label="City" value={p.city} onChange={(v) => set({ city: v })} />
        <Text label="State" value={p.state} onChange={(v) => set({ state: v })} />
        <Text label="ZIP code" value={p.postal} inputMode="numeric"
          onChange={(v) => set({ postal: v })} />
      </div>
      <Text label="Square footage (optional)" inputMode="numeric"
        value={p.square_feet ? String(p.square_feet) : ""}
        onChange={(v) => set({ square_feet: v.replace(/[^\d]/g, "")
          ? Number(v.replace(/[^\d]/g, "")) : null })} />
      <Select label="What kind of property is it?" value={p.lodging_type_id ?? ""}
        options={ctx.form.lodging_types.map((t) => ({ value: String(t.id), label: t.name }))}
        onChange={(v) => set({ lodging_type_id: v ? Number(v) : null })} />
      <Choice label="When will it be ready for our team to start onboarding?"
        hint="Ready means furnished, ready for photos, with no major repairs to do."
        options={opts(ctx.form, "ready")} value={p.ready}
        onChange={(v) => set({ ready: v })} />
      {p.ready === "date" && (
        <Text label="Ready date" type="date" value={p.ready_date}
          onChange={(v) => set({ ready_date: v })} />
      )}
      <YesNo label="Does it have bookings already, through a former manager?"
        value={p.has_bookings} onChange={(v) => set({ has_bookings: v })} />
      {p.has_bookings === "yes" && (
        <Ranges label="Dates already booked" ranges={p.bookings} addLabel="Add booked dates"
          onChange={(r) => set({ bookings: r })} />
      )}
      <GenericFields ctx={ctx} section="property" />
    </>
  );
}

// ------------------------------------------------------------ beds

function Beds({ ctx, beds, onChange, otherPlaces }: {
  ctx: Ctx; beds: Bed[]; onChange: (b: Bed[]) => void; otherPlaces?: boolean;
}) {
  const types = ctx.form.bed_types.filter((t) => !otherPlaces || t.other_places);
  return (
    <div className="ix-beds">
      {beds.map((b, i) => (
        <div key={i} className="ix-bed">
          <select className="ix-input ix-select" aria-label={`Bed ${i + 1} type`}
            value={b.type || ""}
            onChange={(e) => onChange(beds.map((x, j) => (j === i ? { ...x, type:
              Number(e.target.value) } : x)))}>
            <option value="">Choose a bed</option>
            {types.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
          <Stepper label={b.type ? bedLabel(ctx.form, b.type) : `bed ${i + 1}`} value={b.count}
            min={1} onChange={(n) => onChange(beds.map((x, j) => (j === i ? { ...x, count: n }
              : x)))} />
          <button type="button" className="ix-link ix-remove" aria-label={`Remove bed ${i + 1}`}
            onClick={() => onChange(beds.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <button type="button" className="ix-btn ix-btn-ghost"
        onClick={() => onChange([...beds, { type: 0, count: 1 }])}>+ Add a bed</button>
    </div>
  );
}

export function BedroomsSection({ ctx }: { ctx: Ctx }) {
  const rooms = ctx.answers.bedrooms ?? [];
  const set = (next: typeof rooms) => ctx.update("bedrooms", next);
  return (
    <>
      {rooms.map((room, i) => (
        <Block key={i} title={`Bedroom ${i + 1}`}
          summary={roomSummary(ctx.form, `Bedroom ${i + 1}`, room.beds.filter((b) => b.type))}
          onRemove={() => set(rooms.filter((_, j) => j !== i))} removeLabel="Remove bedroom">
          <Beds ctx={ctx} beds={room.beds}
            onChange={(beds) => set(rooms.map((x, j) => (j === i ? { ...x, beds } : x)))} />
          <label className={`ix-card ix-check ix-wide${room.own_bath ? " ix-on" : ""}`}>
            <input type="checkbox" checked={room.own_bath} onChange={() =>
              set(rooms.map((x, j) => (j === i ? { ...x, own_bath: !x.own_bath } : x)))} />
            <span>This bedroom has its own bathroom</span>
          </label>
        </Block>
      ))}
      <button type="button" className="ix-btn ix-btn-ghost ix-btn-big"
        onClick={() => set([...rooms, { beds: [{ type: 0, count: 1 }], own_bath: false }])}>
        + Add a bedroom</button>
    </>
  );
}

export function OtherSleepingSection({ ctx }: { ctx: Ctx }) {
  const o = ctx.answers.other_sleeping ?? {};
  const places = o.places ?? [];
  const set = (patch: Partial<typeof o>) => ctx.update("other_sleeping", { ...o, ...patch });
  const setPlace = (i: number, patch: Partial<Place>) =>
    set({ places: places.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
  return (
    <>
      <YesNo label="Can people sleep anywhere besides the bedrooms?"
        hint="A sofa bed in the living room, a futon in the den, a Murphy bed in a loft."
        value={o.has} onChange={(v) => set({
          has: v, places: v === "yes" && !places.length
            ? [{ where: "", label: "", beds: [{ type: 0, count: 1 }] }] : places,
        })} />
      {o.has === "yes" && (
        <>
          {places.map((place, i) => (
            <Block key={i} title={`Sleeping place ${i + 1}`}
              summary={roomSummary(ctx.form, label(ctx.form, "where", place.where) || "Where",
                place.beds.filter((b) => b.type))}
              onRemove={() => set({ places: places.filter((_, j) => j !== i) })}>
              <Select label="Where is it?" options={opts(ctx.form, "where")} value={place.where}
                onChange={(v) => setPlace(i, { where: v })} />
              {place.where === "other" && (
                <Text label="Which room?" value={place.label}
                  onChange={(v) => setPlace(i, { label: v })} />
              )}
              <Beds ctx={ctx} beds={place.beds} otherPlaces
                onChange={(beds) => setPlace(i, { beds })} />
            </Block>
          ))}
          <button type="button" className="ix-btn ix-btn-ghost" onClick={() => set({
            places: [...places, { where: "", label: "", beds: [{ type: 0, count: 1 }] }],
          })}>+ Add another place</button>
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------ bathrooms

const MAIN_FIXTURES = ["Toilet", "Sink", "Shower", "Bathtub", "Combo Bathtub & Shower",
  "Jetted Bathtub", "Outdoor Shower", "Bidet"];

export function BathroomsSection({ ctx }: { ctx: Ctx }) {
  const baths = ctx.answers.bathrooms ?? [];
  const set = (next: typeof baths) => ctx.update("bathrooms", next);
  const fixtures = ctx.form.bathroom_fixtures;
  const main = MAIN_FIXTURES.map((n) => fixtures.find((f) => f.name === n))
    .filter((f): f is (typeof fixtures)[number] => !!f);
  const access = fixtures.filter((f) => !MAIN_FIXTURES.includes(f.name));
  const row = (i: number, f: (typeof fixtures)[number]) => {
    const count = baths[i].fixtures[String(f.id)] ?? 0;
    const setCount = (n: number) => set(baths.map((b, j) => {
      if (j !== i) return b;
      const next = { ...b.fixtures };
      if (n > 0) next[String(f.id)] = n; else delete next[String(f.id)];
      return { fixtures: next };
    }));
    return (
      <div key={f.id} className={`ix-fixture${count ? " ix-on" : ""}`}>
        <label className="ix-fixture-name">
          <input type="checkbox" checked={count > 0} onChange={() => setCount(count ? 0 : 1)} />
          <span>{f.name}</span>
        </label>
        {count > 0 && <Stepper label={f.name} value={count} min={1} max={9}
          onChange={setCount} />}
      </div>
    );
  };
  return (
    <>
      <p className="ix-lead">Tick what's in each bathroom. Two sinks? Set Sink to 2.</p>
      {baths.map((b, i) => (
        <Block key={i} title={`Bathroom ${i + 1}`}
          summary={bathSummary(ctx.form, `Bathroom ${i + 1}`, b.fixtures)}
          onRemove={() => set(baths.filter((_, j) => j !== i))} removeLabel="Remove bathroom">
          <div className="ix-fixtures">{main.map((f) => row(i, f))}</div>
          {access.length > 0 && (
            <details className="ix-more">
              <summary>Accessibility features</summary>
              <div className="ix-fixtures">{access.map((f) => row(i, f))}</div>
            </details>
          )}
        </Block>
      ))}
      <button type="button" className="ix-btn ix-btn-ghost ix-btn-big"
        onClick={() => set([...baths, { fixtures: {} }])}>+ Add a bathroom</button>
    </>
  );
}

// ------------------------------------------------------------ amenities

export function AmenitiesSection({ ctx }: { ctx: Ctx }) {
  const a = ctx.answers.amenities ?? {};
  const set = (patch: Partial<typeof a>) => ctx.update("amenities", { ...a, ...patch });
  const more = new Set(a.more ?? []);
  const [open, setOpen] = useState(more.size > 0);
  return (
    <>
      <Checks label="Which of these does the home have?"
        hint="Tick any you have now, or are adding."
        options={ctx.form.common_amenities.map((c) => ({ value: c.key, label: c.label }))}
        values={a.common} onChange={(v) => set({ common: v })} />
      <YesNo label="Gondola or lift access?" value={a.gondola}
        onChange={(v) => set({ gondola: v })} />
      {!open ? (
        <button type="button" className="ix-btn ix-btn-ghost" onClick={() => setOpen(true)}>
          Anything more? See every amenity</button>
      ) : (
        <div className="ix-groups">
          <p className="ix-label">Anything more?</p>
          {ctx.form.amenity_groups.map((g) => {
            const ticked = g.amenities.filter((x) => more.has(x.id)).length;
            return (
              <details key={g.name} className="ix-more">
                <summary>{g.name}{ticked ? ` · ${ticked} ticked` : ""}</summary>
                <div className="ix-cards">
                  {g.amenities.map((x) => (
                    <label key={x.id} className={`ix-card ix-check${more.has(x.id) ? " ix-on"
                      : ""}`}>
                      <input type="checkbox" checked={more.has(x.id)} onChange={() => {
                        const next = new Set(more);
                        if (next.has(x.id)) next.delete(x.id); else next.add(x.id);
                        set({ more: [...next] });
                      }} />
                      <span>{x.name}</span>
                    </label>
                  ))}
                </div>
              </details>
            );
          })}
        </div>
      )}
      <GenericFields ctx={ctx} section="amenities" />
    </>
  );
}

// ------------------------------------------------------------ home details

export function HomeSection({ ctx }: { ctx: Ctx }) {
  const h: Home = ctx.answers.home ?? {};
  const set = (patch: Partial<Home>) => ctx.update("home", { ...h, ...patch });
  const on = (ref: string) => ctx.form.builtin[`pms_units_${ref}`] !== false;
  const f = ctx.form;
  return (
    <>
      {on("hvac_notes") && (
        <Block title="Heating and cooling">
          <Checks label="How is the home heated?" options={opts(f, "heating")} values={h.heating}
            onChange={(v) => set({ heating: v })} />
          <Checks label="How is it cooled?" options={opts(f, "cooling")} values={h.cooling}
            onChange={(v) => set({ cooling: v })} />
          <Area label="Anything we should know? (optional)" value={h.hvac_note} rows={2}
            hint="If you don't know, that's fine." onChange={(v) => set({ hvac_note: v })} />
        </Block>
      )}
      {on("parking_instructions") && (
        <Block title="Parking">
          <Checks label="Where do guests park?" options={opts(f, "parking")} values={h.parking}
            onChange={(v) => set({ parking: v })} />
          <YesNo label="Do guests need a parking pass that has to be returned?"
            value={h.parking_pass} onChange={(v) => set({ parking_pass: v })} />
          <Area label="Parking notes (optional)" value={h.parking_note} rows={2}
            onChange={(v) => set({ parking_note: v })} />
        </Block>
      )}
      {(on("wifi_network_name") || on("internet_service_provider")) && (
        <Block title="Wi-Fi and internet">
          <YesNo label="Is there Wi-Fi?" value={h.wifi} onChange={(v) => set({ wifi: v })} />
          {h.wifi === "yes" && (
            <>
              {on("internet_service_provider") && <Text label="Internet provider"
                value={h.wifi_provider} onChange={(v) => set({ wifi_provider: v })} />}
              {on("wifi_network_name") && <Text label="Wi-Fi network name" value={h.wifi_network}
                autoComplete="off" onChange={(v) => set({ wifi_network: v })} />}
              {on("wifi_password") && (
                <>
                  <SecretField label="Wi-Fi password" name="wifi_password"
                    hint="Kept apart from your other answers, and not shown again here."
                    saved={ctx.secrets.wifi_password}
                    onSave={async (v) => ctx.setSecrets(await ctx.api.putSecret("wifi_password",
                      "", v))}
                    onClear={async () => ctx.setSecrets(await ctx.api.clearSecret(
                      "wifi_password", ""))} />
                  <Needed ctx={ctx} name="wifi_password" label="Wi-Fi password" />
                </>
              )}
              {on("wifi_router_location_notes") && <Text label="Where is the router?"
                value={h.wifi_router} onChange={(v) => set({ wifi_router: v })} />}
            </>
          )}
        </Block>
      )}
      {on("cable_or_satellite_tv_notes") && (
        <Block title="TV and entertainment">
          <Checks label="What's there?" options={opts(f, "tv")} values={h.tv}
            onChange={(v) => set({ tv: v })} />
          {(h.tv ?? []).length > 0 && (
            <>
              <Field label="How many TVs?">
                <Stepper label="TVs" value={h.tv_count || 1} min={1}
                  onChange={(n) => set({ tv_count: n })} />
              </Field>
              {on("cable_or_satellite_tv_provider") && <Text label="TV provider (optional)"
                value={h.tv_provider} onChange={(v) => set({ tv_provider: v })} />}
              <Area label="Anything else about the setup? (optional)" value={h.tv_note} rows={2}
                onChange={(v) => set({ tv_note: v })} />
            </>
          )}
        </Block>
      )}
      {on("trash_service_provider") && (
        <Block title="Trash and recycling">
          <Choice label="Who collects the trash?" options={opts(f, "trash_by")} value={h.trash_by}
            onChange={(v) => set({ trash_by: v })} />
          {h.trash_by === "company" && <Text label="Which company?" value={h.trash_provider}
            onChange={(v) => set({ trash_provider: v })} />}
          {h.trash_by && h.trash_by !== "unsure" && on("trash_pickup_day")
            && f.trash_days.length > 0 && (
            <Checks label="Pickup days" options={f.trash_days} values={h.trash_days}
              onChange={(v) => set({ trash_days: v })} />
          )}
          {on("trash_notes") && <Area label="Trash notes (optional)" value={h.trash_note} rows={2}
            onChange={(v) => set({ trash_note: v })} />}
        </Block>
      )}
      {on("hoa_management_company_name") && (
        <Block title="HOA">
          <YesNo label="Is the home in an HOA?" unsure value={h.hoa}
            onChange={(v) => set({ hoa: v })} />
          {h.hoa === "yes" && (
            <>
              <Text label="Management company" value={h.hoa_company}
                onChange={(v) => set({ hoa_company: v })} />
              <Text label="Contact person" value={h.hoa_contact}
                onChange={(v) => set({ hoa_contact: v })} />
              <div className="ix-two">
                <Text label="Phone" type="tel" inputMode="tel" value={h.hoa_phone}
                  onChange={(v) => set({ hoa_phone: v })} />
                <Text label="Email" type="email" inputMode="email" value={h.hoa_email}
                  onChange={(v) => set({ hoa_email: v })} />
              </div>
              <Area label="Anything else about the HOA? (optional)" value={h.hoa_note} rows={2}
                onChange={(v) => set({ hoa_note: v })} />
            </>
          )}
        </Block>
      )}
      {on("heat_tape_notes") && (
        <Block title="Heat tape">
          <YesNo label="Does the property have heat tape?" unsure value={h.heat_tape}
            onChange={(v) => set({ heat_tape: v })} />
          {h.heat_tape === "yes" && <Text label="Who maintains it?" value={h.heat_tape_by}
            onChange={(v) => set({ heat_tape_by: v })} />}
        </Block>
      )}
      {on("snow_plowing_provider") && (
        <Block title="Snow removal">
          <Choice label="Who takes care of snow removal?" options={opts(f, "done_by")}
            value={h.snow_by} onChange={(v) => set({ snow_by: v })} />
          {h.snow_by === "company" && <Text label="Which company? (name and phone)"
            value={h.snow_provider} onChange={(v) => set({ snow_provider: v })} />}
          {h.snow_by && <Area label="Snow removal notes (optional)" value={h.snow_note} rows={2}
            onChange={(v) => set({ snow_note: v })} />}
        </Block>
      )}
      {on("landscaping") && (
        <Block title="Landscaping">
          <Choice label="Who takes care of the landscaping?" options={opts(f, "done_by")}
            value={h.landscaping_by} onChange={(v) => set({ landscaping_by: v })} />
          {h.landscaping_by && <Area label="Landscaping notes (optional)"
            value={h.landscaping_note} rows={2}
            onChange={(v) => set({ landscaping_note: v })} />}
        </Block>
      )}
      {on("water_softener") && (
        <Block title="Water softener">
          <YesNo label="Is there a water softener?" unsure value={h.softener}
            onChange={(v) => set({ softener: v })} />
          {h.softener === "yes" && <Area label="Where is it, and who services it?"
            value={h.softener_note} rows={2} onChange={(v) => set({ softener_note: v })} />}
        </Block>
      )}
      {on("nightly_rental_permit") && (
        <Block title="Rental permit">
          <YesNo label="Does the property have a current nightly rental permit?" unsure
            value={h.permit} onChange={(v) => set({ permit: v })} />
          {h.permit === "yes" && <Text label="Permit number" value={h.permit_number}
            onChange={(v) => set({ permit_number: v })} />}
        </Block>
      )}
      <GenericFields ctx={ctx} section="home" />
    </>
  );
}

// ------------------------------------------------------------ getting in

export function AccessSection({ ctx }: { ctx: Ctx }) {
  const a: Access = ctx.answers.access ?? {};
  const set = (patch: Partial<Access>) => ctx.update("access", { ...a, ...patch });
  const extras = a.extra_codes ?? [];
  const you = ctx.mode === "owner";
  const code = (slot: string, title: string, needed: string = title) => (
    <div key={slot}>
      <SecretField label={title} inputMode="text" name={`code:${slot}`}
        hint="Kept apart from your other answers, and not shown again here."
        saved={!!ctx.secrets.codes[slot]}
        onSave={async (v) => ctx.setSecrets(await ctx.api.putSecret("code", slot, v))}
        onClear={async () => ctx.setSecrets(await ctx.api.clearSecret("code", slot))} />
      <Needed ctx={ctx} name={`code:${slot}`} label={needed} />
    </div>
  );
  return (
    <>
      <Choice label="How do guests get in the front door?" options={opts(ctx.form, "door")}
        value={a.door} onChange={(v) => set({ door: v })} />
      {(a.door === "smart_lock" || a.door === "keypad") && code("door", "Door code")}
      {a.door === "lockbox" && code("door", "Lockbox code")}
      <Choice label="Is there a locked owner's closet?" options={opts(ctx.form, "owner_closet")}
        hint={you ? "If it opens with a key, there's no code to enter." : undefined}
        value={withCode(a.owner_closet)} onChange={(v) => set({ owner_closet: v })} />
      {withCode(a.owner_closet) === "code" && code("owner_closet", "Owner's closet code",
        "Owner closet code")}
      <Choice label="Does the property have an alarm?" options={opts(ctx.form, "alarm")}
        value={withCode(a.alarm)} onChange={(v) => set({ alarm: v })} />
      {withCode(a.alarm) === "code" && code("alarm", "Alarm code")}
      {extras.map((x, i) => (
        <Block key={i} title={`Other code ${i + 1}`}
          onRemove={i === extras.length - 1 ? async () => {
            ctx.setSecrets(await ctx.api.clearSecret("code", `extra-${i}`));
            set({ extra_codes: extras.slice(0, -1) });
          } : undefined}>
          <Select label="What is it for?" value={x.type || ""}
            options={ctx.form.code_types.map((t) => ({ value: String(t.id), label: t.name }))}
            onChange={(v) => set({ extra_codes: extras.map((e, j) => (j === i ? { type:
              Number(v) } : e)) })} />
          {x.type > 0 && code(`extra-${i}`, "Code", ctx.form.code_types.find((t) =>
            t.id === x.type)?.name ?? "Code")}
        </Block>
      ))}
      <button type="button" className="ix-btn ix-btn-ghost"
        onClick={() => set({ extra_codes: [...extras, { type: 0 }] })}>
        + Add another code (garage, gate, pool…)</button>
    </>
  );
}

// ------------------------------------------------------------ your own stays

export function StaysSection({ ctx }: { ctx: Ctx }) {
  const s = ctx.answers.stays ?? {};
  const set = (patch: Partial<typeof s>) => ctx.update("stays", { ...s, ...patch });
  return (
    <>
      <YesNo label="Are there dates you'd like to keep for your own use?" value={s.has}
        onChange={(v) => set({ has: v, ranges: v === "yes" && !(s.ranges ?? []).length
          ? [{ start: "", end: "" }] : s.ranges })} />
      {s.has === "yes" && (
        <>
          <Ranges label="Your dates" ranges={s.ranges} addLabel="Add more dates"
            onChange={(r) => set({ ranges: r })} />
          <Note>We'll hold these for you and block them on the calendar as soon as your
            listing opens for bookings.</Note>
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------ documents

export function DocumentsSection({ ctx }: { ctx: Ctx }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <>
      <p className="ix-lead">Your insurance declarations page, showing {ctx.brand} added to the
        policy. Don't have it yet? That's fine; we can get it later.</p>
      {ctx.files.length > 0 && (
        <ul className="ix-files">
          {ctx.files.map((file) => (
            <li key={file.id}>
              {ctx.api.fileUrl ? <a href={ctx.api.fileUrl(file.id)} target="_blank"
                rel="noreferrer">{file.name}</a> : <span>{file.name}</span>}
              <span className="ix-muted"> · {Math.max(1, Math.round(file.size / 1024))} KB</span>
              <button type="button" className="ix-link ix-remove" onClick={async () => {
                await ctx.api.deleteFile(file.id);
                ctx.setFiles(ctx.files.filter((x) => x.id !== file.id));
              }}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      {ctx.files.length < 5 && (
        <Field label="Upload a file" hint="PDF, JPG, PNG or HEIC, up to 15 MB. Up to 5 files."
          error={error}>
          <input className="ix-file" type="file" accept=".pdf,.jpg,.jpeg,.png,.heic,image/*,application/pdf"
            disabled={busy} aria-label="Upload a file" onChange={async (e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (!file) return;
              setError("");
              setBusy(true);
              try {
                const row = await ctx.api.uploadFile(file);
                ctx.setFiles([...ctx.files, row]);
              } catch (err) {
                setError((err as Error).message);
              } finally {
                setBusy(false);
              }
            }} />
          {busy && <p className="ix-hint" aria-live="polite">Uploading…</p>}
        </Field>
      )}
    </>
  );
}

// ------------------------------------------------------------ the list

export const SECTIONS: Record<string, (props: { ctx: Ctx }) => ReactElement> = {
  about: AboutSection, tax: TaxSection, property: PropertySection, bedrooms: BedroomsSection,
  other_sleeping: OtherSleepingSection, bathrooms: BathroomsSection,
  amenities: AmenitiesSection, home: HomeSection, access: AccessSection, stays: StaysSection,
  documents: DocumentsSection,
};

export const INTROS: Record<string, string> = {
  about: "Tell us who you are and how to reach you.",
  tax: "One question, so your year-end tax forms are right.",
  property: "Where it is, and when it's ready.",
  bedrooms: "Add each bedroom and its beds.",
  other_sleeping: "Sofa beds, futons and Murphy beds outside the bedrooms.",
  bathrooms: "Add each bathroom and what's in it.",
  amenities: "What makes the home great for guests.",
  home: "The practical details. If you don't know something, skip it.",
  access: "How our team and your guests get in.",
  stays: "Times you'd like to keep for yourself.",
  documents: "One document, if you have it handy.",
};

/** The review page's lines for a section. */
export function summarize(ctx: Ctx, key: string): string[] {
  const a: Answers = ctx.answers;
  const f = ctx.form;
  switch (key) {
    case "about": {
      const x = a.about ?? {};
      const lines = [
        [x.first_name, x.last_name].filter(Boolean).join(" "),
        x.account_name && x.account_name !== `${x.first_name} ${x.last_name}`
          ? `Account: ${x.account_name}` : "",
        [x.street, x.street2, x.city, x.state, x.postal].filter(Boolean).join(", "),
        [x.mobile, x.email].filter(Boolean).join(" · "),
        x.contact_pref ? `Prefers: ${label(f, "contact_pref", x.contact_pref)}` : "",
        x.emergency?.name || x.emergency?.phone ? `Emergency contact: ${[x.emergency?.name,
          x.emergency?.phone].filter(Boolean).join(", ")}` : "",
      ];
      for (const o of x.has_extra_owners === "yes" ? x.extra_owners ?? [] : [])
        lines.push(`Also an owner: ${[o.first_name, o.last_name].filter(Boolean).join(" ")}`);
      return lines.filter(Boolean);
    }
    case "tax": {
      const kind = a.tax?.kind;
      if (kind === "tax_id")
        return [ctx.secrets.tax_id ? `Business Tax ID ending ${ctx.secrets.tax_id.last4}`
          : "Business Tax ID (not entered yet)"];
      return kind === "ssn" ? ["Social Security number: you'll add it in the owner portal"] : [];
    }
    case "property": {
      const p = a.property ?? {};
      const type = f.lodging_types.find((t) => t.id === p.lodging_type_id)?.name;
      return [[p.street, p.street2, p.city, p.state, p.postal].filter(Boolean).join(", "),
        p.square_feet ? `${p.square_feet.toLocaleString("en-US")} sq ft` : "",
        type ? `Type: ${type}` : "",
        p.ready ? `Ready: ${p.ready === "date" ? p.ready_date : label(f, "ready", p.ready)}` : "",
        p.has_bookings === "yes" ? `${(p.bookings ?? []).length} booked date range(s)` : "",
      ].filter(Boolean);
    }
    case "bedrooms":
      return [...(a.bedrooms ?? []).map((r, i) => roomSummary(f, `Bedroom ${i + 1}`,
        r.beds.filter((b) => b.type)) + (r.own_bath ? ", own bathroom" : "")),
        `Sleeps ${totalSleeps(f, a)} in all`];
    case "other_sleeping":
      return a.other_sleeping?.has === "yes" ? (a.other_sleeping.places ?? []).map((p) =>
        roomSummary(f, label(f, "where", p.where) || "Sleeping place",
          p.beds.filter((b) => b.type))) : ["None"];
    case "bathrooms":
      return (a.bathrooms ?? []).map((b, i) => bathSummary(f, `Bathroom ${i + 1}`, b.fixtures));
    case "amenities": {
      const common = labels({ ...f, options: { c: f.common_amenities.map((c) => ({
        value: c.key, label: c.label })) } }, "c", a.amenities?.common);
      const more = (a.amenities?.more ?? []).length;
      return [common, more ? `${more} more` : "",
        a.amenities?.gondola === "yes" ? "Gondola or lift access" : ""].filter(Boolean);
    }
    case "home": {
      const h = a.home ?? {};
      return [h.heating?.length ? `Heating: ${labels(f, "heating", h.heating)}` : "",
        h.cooling?.length ? `Cooling: ${labels(f, "cooling", h.cooling)}` : "",
        h.wifi ? `Wi-Fi: ${label(f, "yes_no", h.wifi)}` : "",
        h.wifi === "yes" && f.builtin["pms_units_wifi_password"] !== false
          && !ctx.secrets.wifi_password
          ? "Wi-Fi password (not entered yet)" : "",
        h.hoa ? `HOA: ${label(f, "yes_no_unsure", h.hoa)}` : "",
        h.permit === "yes" ? "Has a rental permit" : ""].filter(Boolean);
    }
    case "access": {
      const x = a.access ?? {};
      const slots = codeSlots(x);
      const n = slots.filter((s) => ctx.secrets.codes[s]).length;
      const names: Record<string, string> = { door: x.door === "lockbox" ? "lockbox code"
        : "door code", owner_closet: "owner's closet code", alarm: "alarm code" };
      const waiting = slots.filter((s) => !ctx.secrets.codes[s])
        .map((s) => names[s] ?? "another code");
      return [x.door ? `Front door: ${label(f, "door", x.door)}` : "",
        x.owner_closet ? `Owner's closet: ${label(f, "owner_closet", withCode(x.owner_closet))}`
          : "",
        x.alarm ? `Alarm: ${label(f, "alarm", withCode(x.alarm))}` : "",
        n ? `${n} code(s) saved securely` : "",
        waiting.length ? `Not entered yet: ${[...new Set(waiting)].join(", ")}` : "",
      ].filter(Boolean);
    }
    case "stays":
      return a.stays?.has === "yes" ? (a.stays.ranges ?? []).filter((r) => r.start)
        .map((r) => `${r.start} to ${r.end || "?"}`) : ["None"];
    case "documents":
      return ctx.files.length ? ctx.files.map((x) => x.name) : ["Nothing uploaded yet"];
    default:
      return [];
  }
}

export { bathType };
