import { fetchActivities, registerForActivity, type Activity, type CustomField } from "./api";
import { formatDutchDate } from "./format";

let activitiesBySlug = new Map<string, Activity>();

function escapeHtml(value: string): string {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

// Convert a supported video URL to an embeddable iframe src. Only known
// providers are matched (the src is rebuilt from a captured id), so a
// board-pasted URL can't inject an arbitrary iframe target.
function videoEmbedSrc(url: string): string | null {
  const instagram = url.match(/instagram\.com\/(?:p|reel|tv)\/([A-Za-z0-9_-]+)/);
  if (instagram) return `https://www.instagram.com/p/${instagram[1]}/embed`;
  const youtube = url.match(/(?:youtube\.com\/(?:watch\?v=|embed\/)|youtu\.be\/)([A-Za-z0-9_-]+)/);
  if (youtube) return `https://www.youtube.com/embed/${youtube[1]}`;
  return null;
}

function renderRegistrationControl(activity: Activity): string {
  // No date yet = "to be announced": show a teaser message, no signup UI.
  if (!activity.date) {
    return `<p class="activity-card__status activity-card__status--tba">Meer info volgt — houd onze socials in de gaten!</p>`;
  }

  if (!activity.requires_registration) {
    return `<p class="activity-card__status">Aanmelden niet nodig — kom gewoon langs!</p>`;
  }

  if (activity.external_registration_url) {
    return `<a class="button" href="${escapeHtml(activity.external_registration_url)}" target="_blank" rel="noopener noreferrer">Inschrijven</a>`;
  }

  if (!activity.registration_open) {
    return `<p class="activity-card__status activity-card__status--closed">Inschrijving gesloten</p>`;
  }

  if (activity.is_full) {
    return `
      <p class="activity-card__status activity-card__status--full">Vol — schrijf je in voor de wachtlijst</p>
      <button type="button" class="button" data-register-slug="${escapeHtml(activity.slug)}">Inschrijven</button>
    `;
  }

  const spotsText =
    activity.capacity !== null ? `<p class="activity-card__status">Nog ${activity.spots_remaining} plekken</p>` : "";

  return `
    ${spotsText}
    <button type="button" class="button" data-register-slug="${escapeHtml(activity.slug)}">Inschrijven</button>
  `;
}

function renderCard(activity: Activity): string {
  const embedSrc = activity.video_url ? videoEmbedSrc(activity.video_url) : null;
  const featured = embedSrc !== null;

  let mediaHtml = "";
  if (embedSrc) {
    mediaHtml = `<div class="activity-card__video"><iframe src="${escapeHtml(embedSrc)}" title="Video: ${escapeHtml(activity.title)}" loading="lazy" allowfullscreen scrolling="no"></iframe></div>`;
  } else if (activity.image) {
    mediaHtml = `<img src="${escapeHtml(activity.image)}" alt="" class="activity-card__image" loading="lazy" />`;
  }

  const dateHtml = activity.date
    ? `<p class="activity-card__date">${escapeHtml(formatDutchDate(activity.date))}</p>`
    : `<p class="activity-card__date activity-card__date--tba">Datum volgt</p>`;
  const themeHtml = activity.theme ? `<p class="activity-card__theme">${escapeHtml(activity.theme)}</p>` : "";
  const timeHtml = activity.time_text ? `<p class="activity-card__time">${escapeHtml(activity.time_text)}</p>` : "";
  const locationHtml = activity.location_text
    ? `<p class="activity-card__location">${escapeHtml(activity.location_text)}</p>`
    : "";
  const costHtml = activity.cost_note
    ? `<p class="activity-card__cost">${escapeHtml(activity.cost_note)}</p>`
    : "";
  const descriptionHtml = activity.description
    ? `<p class="activity-card__description">${escapeHtml(activity.description)}</p>`
    : "";
  // Video present but from an unsupported provider: link out instead of embed.
  const videoLinkHtml =
    activity.video_url && !embedSrc
      ? `<p><a href="${escapeHtml(activity.video_url)}" target="_blank" rel="noopener noreferrer">Bekijk de video</a></p>`
      : "";

  return `
    <article class="activity-card${featured ? " activity-card--featured" : ""}" data-activity-slug="${escapeHtml(activity.slug)}">
      ${mediaHtml}
      <div class="activity-card__body">
        <h3>${escapeHtml(activity.title)}</h3>
        ${dateHtml}
        ${themeHtml}
        ${timeHtml}
        ${locationHtml}
        ${descriptionHtml}
        ${videoLinkHtml}
        ${costHtml}
        <div class="activity-card__registration">
          ${renderRegistrationControl(activity)}
        </div>
      </div>
    </article>
  `;
}

async function loadActivities() {
  const container = document.getElementById("activity-list");
  if (!container) return;

  try {
    const activities = await fetchActivities();
    activitiesBySlug = new Map(activities.map((a) => [a.slug, a]));

    if (activities.length === 0) {
      container.innerHTML = `<p class="programma__empty">Er zijn nog geen activiteiten gepubliceerd.</p>`;
      return;
    }

    container.innerHTML = activities.map(renderCard).join("");
  } catch (err) {
    container.innerHTML = `<p class="programma__error">Kon activiteiten niet laden. Probeer de pagina te verversen.</p>`;
  }
}

function renderCustomField(field: CustomField): string {
  const requiredAttr = field.required ? "required" : "";
  const requiredMark = field.required ? "*" : "";
  const label = `${escapeHtml(field.label)}${requiredMark}`;

  let inputHtml = "";
  switch (field.type) {
    case "textarea":
      inputHtml = `<textarea name="custom__${escapeHtml(field.key)}" ${requiredAttr}></textarea>`;
      break;
    case "select": {
      const options = (field.options || [])
        .map((opt) => `<option value="${escapeHtml(opt)}">${escapeHtml(opt)}</option>`)
        .join("");
      inputHtml = `<select name="custom__${escapeHtml(field.key)}" ${requiredAttr}>
        <option value="">Maak een keuze</option>
        ${options}
      </select>`;
      break;
    }
    case "checkbox":
      return `
        <label class="custom-field custom-field--checkbox">
          <input type="checkbox" name="custom__${escapeHtml(field.key)}" ${requiredAttr} />
          ${label}
          <span class="field-error" data-error-for="${escapeHtml(field.key)}"></span>
        </label>
      `;
    case "number":
      inputHtml = `<input type="number" name="custom__${escapeHtml(field.key)}" ${requiredAttr} />`;
      break;
    default:
      inputHtml = `<input type="text" name="custom__${escapeHtml(field.key)}" ${requiredAttr} />`;
  }

  return `
    <label class="custom-field">
      ${label}
      ${inputHtml}
      <span class="field-error" data-error-for="${escapeHtml(field.key)}"></span>
    </label>
  `;
}

function clearFormErrors(form: HTMLFormElement) {
  form.querySelectorAll<HTMLElement>(".field-error").forEach((el) => (el.textContent = ""));
  const generalError = document.getElementById("register-modal-error");
  if (generalError) {
    generalError.hidden = true;
    generalError.textContent = "";
  }
}

function openModalForActivity(slug: string) {
  const activity = activitiesBySlug.get(slug);
  if (!activity) return;

  const modal = document.getElementById("register-modal") as HTMLDialogElement | null;
  const form = document.getElementById("register-form") as HTMLFormElement | null;
  const formView = document.getElementById("register-modal-form-view");
  const successView = document.getElementById("register-modal-success-view");
  const title = document.getElementById("register-modal-title");
  if (!modal || !form || !formView || !successView || !title) return;

  formView.hidden = false;
  successView.hidden = true;
  form.reset();
  clearFormErrors(form);

  title.textContent = `Inschrijven: ${activity.title}`;
  form.dataset.slug = activity.slug;

  form.querySelector(".field-phone")!.toggleAttribute("hidden", !activity.collect_phone);
  form.querySelector(".field-phone input")!.toggleAttribute("required", false);
  form.querySelector(".field-study")!.toggleAttribute("hidden", !activity.collect_study);
  form.querySelector(".field-dietary")!.toggleAttribute("hidden", !activity.collect_dietary);

  const customContainer = document.getElementById("custom-fields-container");
  if (customContainer) {
    customContainer.innerHTML = activity.custom_fields.map(renderCustomField).join("");
  }

  modal.showModal();
}

function collectPayload(form: HTMLFormElement, activity: Activity) {
  const formData = new FormData(form);
  const answers: Record<string, unknown> = {};
  for (const field of activity.custom_fields) {
    const raw = formData.get(`custom__${field.key}`);
    if (field.type === "checkbox") {
      answers[field.key] = formData.get(`custom__${field.key}`) === "on";
    } else if (raw !== null && raw !== "") {
      answers[field.key] = raw;
    }
  }

  return {
    name: String(formData.get("name") || ""),
    email: String(formData.get("email") || ""),
    phone: String(formData.get("phone") || ""),
    study: String(formData.get("study") || ""),
    dietary: String(formData.get("dietary") || ""),
    consent: formData.get("consent") === "on",
    website: String(formData.get("website") || ""),
    answers,
  };
}

function showSuccess(status: "confirmed" | "waitlist") {
  const formView = document.getElementById("register-modal-form-view");
  const successView = document.getElementById("register-modal-success-view");
  const successTitle = document.getElementById("register-modal-success-title");
  const successMessage = document.getElementById("register-modal-success-message");
  if (!formView || !successView || !successTitle || !successMessage) return;

  formView.hidden = true;
  successView.hidden = false;

  if (status === "confirmed") {
    successTitle.textContent = "Bevestigd!";
    successMessage.textContent = "Je inschrijving is bevestigd. Tot dan!";
  } else {
    successTitle.textContent = "Op de wachtlijst";
    successMessage.textContent =
      "De activiteit zit vol — je staat op de wachtlijst. Het bestuur neemt contact met je op als er een plek vrijkomt.";
  }
}

function showGeneralError(message: string) {
  const generalError = document.getElementById("register-modal-error");
  if (generalError) {
    generalError.textContent = message;
    generalError.hidden = false;
  }
}

function showFieldErrors(form: HTMLFormElement, errors: Record<string, string>) {
  let shownInline = false;
  for (const [key, message] of Object.entries(errors)) {
    const target = form.querySelector(`[data-error-for="${CSS.escape(key)}"]`);
    if (target) {
      target.textContent = message;
      shownInline = true;
    } else if (key === "non_field") {
      showGeneralError(message);
      shownInline = true;
    }
  }
  if (!shownInline) {
    showGeneralError(Object.values(errors).join(" "));
  }
}

async function handleSubmit(event: SubmitEvent) {
  event.preventDefault();
  const form = event.currentTarget as HTMLFormElement;
  const slug = form.dataset.slug;
  const activity = slug ? activitiesBySlug.get(slug) : undefined;
  if (!slug || !activity) return;

  clearFormErrors(form);

  const submitButton = document.getElementById("register-submit") as HTMLButtonElement | null;
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.textContent = "Bezig...";
  }

  try {
    const payload = collectPayload(form, activity);
    const result = await registerForActivity(slug, payload);

    if (result.ok) {
      showSuccess(result.status);
      loadActivities();
    } else if (result.kind === "validation") {
      showFieldErrors(form, result.errors);
    } else {
      showGeneralError(result.detail);
    }
  } catch {
    showGeneralError("Er ging iets mis. Probeer het later opnieuw.");
  } finally {
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = "Inschrijven";
    }
  }
}

function initModalHandlers() {
  const modal = document.getElementById("register-modal") as HTMLDialogElement | null;
  const form = document.getElementById("register-form") as HTMLFormElement | null;
  if (!modal || !form) return;

  form.addEventListener("submit", handleSubmit);

  modal.querySelectorAll("[data-close]").forEach((el) => {
    el.addEventListener("click", () => modal.close());
  });

  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      modal.close();
    }
  });
}

function initCardClickDelegation() {
  const container = document.getElementById("activity-list");
  if (!container) return;

  container.addEventListener("click", (event) => {
    const target = event.target as HTMLElement;
    const button = target.closest<HTMLElement>("[data-register-slug]");
    if (button) {
      openModalForActivity(button.dataset.registerSlug!);
    }
  });
}

export function initActivitiesIsland() {
  initModalHandlers();
  initCardClickDelegation();
  loadActivities();
}
