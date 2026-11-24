import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AgreementApp } from "./AgreementApp";
import { FormApp } from "./FormApp";
import "./forms.css";
import { isAgreement, tokenFrom } from "./token";
import type { Brand } from "./types";

/** The page's brand comes from the server (apps/intake/hosts.py), never
 *  from anything of the app's: this bundle is the owner's alone. */
function brand(): Brand {
  const el = document.getElementById("intake-config");
  const fallback: Brand = { brand_name: "", title: "", slug: "", colors: {}, contact_phone: "",
                            contact_email: "", logo: "", icon: "" };
  try {
    return { ...fallback, ...(el ? JSON.parse(el.textContent || "{}") : {}) };
  } catch {
    return fallback;
  }
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {isAgreement(window.location.pathname)
      ? <AgreementApp brand={brand()} token={tokenFrom(window.location.pathname)} />
      : <FormApp brand={brand()} token={tokenFrom(window.location.pathname)} />}
  </StrictMode>,
);
