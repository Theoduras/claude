/* Velvt's service worker. Rendered by Flask at /sw.js, not served from
   /static, so its scope is the whole site -- a worker registered from
   /static/ may only control /static/, and one that cannot open the page it
   is notifying about is no use.

   It does exactly two things, and deliberately nothing else. No fetch
   handler, no caching, no offline shell: a service worker that intercepts
   every request is a second copy of the app's routing living in the
   browser, and this one exists to receive pushes. */

/* Take over as soon as it installs, rather than waiting for every tab using
   the old worker to close. A deploy that changes what a push looks like
   should reach the next push, not the next time somebody quits the app. */
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", function (event) {
  /* The payload is encrypted end to end -- the push service relayed bytes it
     could not read. If it is somehow not the JSON we sent, still show
     something: a browser that receives a push and displays nothing is
     entitled to revoke the permission, so a silent push is a way to lose
     the channel entirely. */
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (err) { data = {}; }

  var title = data.title || "Velvt";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "{{ url_for('static', filename='velvt-icon.svg') }}",
    badge: "{{ url_for('static', filename='velvt-icon.svg') }}",
    /* One notification per kind, replaced rather than stacked. Four
       unanswered messages should be one line on a lock screen. */
    tag: data.kind || "velvt",
    renotify: false,
    data: { url: data.url || "/", id: data.id || null }
  }));
});

self.addEventListener("notificationclick", function (event) {
  event.notification.close();
  var target = (event.notification.data && event.notification.data.url) || "/";

  /* Focus a tab that is already open before opening another one. Someone
     with the chat list already on screen wants that window brought forward,
     not a second copy of the app. */
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true })
      .then(function (windows) {
        for (var i = 0; i < windows.length; i++) {
          if ("focus" in windows[i]) {
            if ("navigate" in windows[i]) { windows[i].navigate(target); }
            return windows[i].focus();
          }
        }
        return self.clients.openWindow(target);
      })
  );
});
