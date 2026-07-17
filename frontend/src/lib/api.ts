export interface CustomField {
  key: string;
  label: string;
  type: "text" | "textarea" | "select" | "checkbox" | "number";
  required?: boolean;
  options?: string[];
}

export interface Activity {
  title: string;
  slug: string;
  date: string | null;
  time_text: string;
  theme: string;
  location_text: string;
  description: string;
  image: string | null;
  video_url: string;
  cost_note: string;
  requires_registration: boolean;
  external_registration_url: string;
  capacity: number | null;
  registration_opens_at: string | null;
  registration_closes_at: string | null;
  collect_phone: boolean;
  collect_study: boolean;
  collect_dietary: boolean;
  custom_fields: CustomField[];
  spots_remaining: number | null;
  is_full: boolean;
  registration_open: boolean;
}

export interface RegisterPayload {
  name: string;
  email: string;
  phone?: string;
  study?: string;
  dietary?: string;
  consent: boolean;
  website?: string;
  answers?: Record<string, unknown>;
}

export type RegisterResult =
  | { ok: true; status: "confirmed" | "waitlist" }
  | { ok: false; kind: "validation"; errors: Record<string, string> }
  | { ok: false; kind: "duplicate" | "closed" | "notfound" | "ratelimited" | "unknown"; detail: string };

export async function fetchActivities(): Promise<Activity[]> {
  const response = await fetch("/api/activities/");
  if (!response.ok) {
    throw new Error(`Kon activiteiten niet laden (${response.status}).`);
  }
  return response.json();
}

export async function registerForActivity(
  slug: string,
  payload: RegisterPayload
): Promise<RegisterResult> {
  const response = await fetch(`/api/activities/${slug}/register/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  let body: any = null;
  try {
    body = await response.json();
  } catch {
    // no body
  }

  if (response.ok) {
    return { ok: true, status: body?.status === "waitlist" ? "waitlist" : "confirmed" };
  }

  if (response.status === 400) {
    if (body?.errors) {
      return { ok: false, kind: "validation", errors: flattenErrors(body.errors) };
    }
    return { ok: false, kind: "validation", errors: { non_field: body?.detail || "Ongeldige inschrijving." } };
  }
  if (response.status === 409) {
    return { ok: false, kind: "duplicate", detail: body?.detail || "Dit e-mailadres is al ingeschreven." };
  }
  if (response.status === 403) {
    return { ok: false, kind: "closed", detail: body?.detail || "Inschrijving is gesloten." };
  }
  if (response.status === 404) {
    return { ok: false, kind: "notfound", detail: body?.detail || "Activiteit niet gevonden." };
  }
  if (response.status === 429) {
    return {
      ok: false,
      kind: "ratelimited",
      detail: body?.detail || "Te veel pogingen. Probeer het later opnieuw.",
    };
  }
  return { ok: false, kind: "unknown", detail: "Er ging iets mis. Probeer het later opnieuw." };
}

function flattenErrors(errors: Record<string, unknown>): Record<string, string> {
  const flat: Record<string, string> = {};
  for (const [key, value] of Object.entries(errors)) {
    if (Array.isArray(value)) {
      flat[key] = value.join(" ");
    } else if (typeof value === "string") {
      flat[key] = value;
    } else {
      flat[key] = String(value);
    }
  }
  return flat;
}
