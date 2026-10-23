import { expect, test, type Page } from "@playwright/test";

const SHOTS = process.env.SCREENSHOTS_DIR; // capture des écrans du README quand défini

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

async function pickFirstDayWithSlots(page: Page) {
  const days = page.locator("main div.flex.gap-2.overflow-x-auto > button");
  const count = await days.count();
  for (let i = 0; i < count; i++) {
    await days.nth(i).click();
    const slots = page.getByTestId("slots");
    const empty = page.getByText("Aucun créneau ce jour-là.");
    await expect(slots.or(empty)).toBeVisible();
    if (await slots.isVisible()) return slots;
  }
  throw new Error("aucun créneau disponible sur 14 jours");
}

test("un client réserve et paie, le gérant voit le rendez-vous", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/studio-zen");
  await expect(page.getByRole("heading", { name: /Studio Zen/ })).toBeVisible();
  await page.getByRole("button", { name: /Cours de yoga individuel/ }).click();
  const slots = await pickFirstDayWithSlots(page);
  await slots.getByRole("button").first().click();
  await page.getByLabel("Nom").fill("Client E2E");
  await page.getByLabel("Email").fill(email);
  await shot(page, "booking-page");
  await page.getByRole("button", { name: /Réserver et payer/ }).click();

  // paiement simulé -> retour sur la page de la réservation, confirmée
  await expect(page.getByTestId("booking-status")).toHaveAttribute("data-status", "confirmed");
  await expect(page.getByRole("heading", { name: "Rendez-vous confirmé" })).toBeVisible();
  await shot(page, "booking-confirmed");

  // côté gérant
  await page.goto("/login?demo=1");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByTestId("bookings-table")).toContainText(email);
  await shot(page, "dashboard");
});

test("un créneau déjà pris n'est plus proposé", async ({ page, request }) => {
  const api = process.env.API_URL ?? "http://localhost:8000";
  const tenant = await (await request.get(`${api}/public/barber-lyon`)).json();
  const service = tenant.services[0];

  await page.goto("/barber-lyon");
  await page.getByRole("button", { name: new RegExp(service.name) }).click();
  const slots = await pickFirstDayWithSlots(page);
  const before = await slots.getByRole("button").count();
  const firstLabel = await slots.getByRole("button").first().textContent();

  // un autre client prend le premier créneau via l'API
  const day = await (async () => {
    const d = new Date();
    for (let i = 0; i < 14; i++) {
      const iso = new Date(d.getFullYear(), d.getMonth(), d.getDate() + i).toLocaleDateString("sv-SE");
      const r = await (await request.get(`${api}/public/barber-lyon/slots?service_id=${service.id}&date=${iso}`)).json();
      if (r.slots.length) return r.slots[0].start as string;
    }
    throw new Error("pas de créneau");
  })();
  const res = await request.post(`${api}/public/barber-lyon/bookings`, {
    data: { service_id: service.id, start: day, customer_name: "Autre", customer_email: "autre@example.com" },
  });
  expect(res.status()).toBe(201);

  await page.reload();
  await page.getByRole("button", { name: new RegExp(service.name) }).click();
  const after = await pickFirstDayWithSlots(page);
  await expect(after.getByRole("button")).toHaveCount(before - 2); // coupe de 30 min : 2 départs de 15 min bloqués
  await expect(after.getByRole("button").first()).not.toHaveText(firstLabel ?? "");
});
