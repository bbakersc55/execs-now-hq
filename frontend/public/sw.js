/* Browser notifications (owner, 2026-10-26). The server sends only what is on
 * the person's Notices list; this shows it, and a click opens the app at the
 * notice's own page (a path in this app, never another site). */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data ? event.data.text() : "" }; }
  const url = typeof data.url === "string" && data.url.startsWith("/") ? data.url : "/";
  event.waitUntil(self.registration.showNotification(data.title || "Execs NOW HQ", {
    body: data.body || "", tag: data.tag || undefined, data: { url },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of open) {
      if (new URL(client.url).origin === self.location.origin && "focus" in client) {
        await client.focus();
        if ("navigate" in client) return client.navigate(url);
        return undefined;
      }
    }
    return self.clients.openWindow(url);
  })());
});
