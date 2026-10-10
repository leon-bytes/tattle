"use strict";
// Tattle show screen: the phone in the middle, one bubble per company it contacts.
// Everything that comes from the API (names, companies, sentences) is put on the page with
// textContent, never as markup: a phone chooses the names it looks up.

const CATEGORIES = [
  {id: "advertising", tag: "AD", label: "advertising"},
  {id: "analytics", tag: "AN", label: "analytics"},
  {id: "social", tag: "SO", label: "social"},
  {id: "fingerprinting", tag: "FP", label: "fingerprinting"},
  {id: "content", tag: "CDN", label: "content delivery"},
  {id: "vendor", tag: "OWN", label: "the phone's or app's own"},
  {id: "unknown", tag: "?", label: "not identified yet"},
];
const TAG = Object.fromEntries(CATEGORIES.map(c => [c.id, c.tag]));
const MAX_HITS = 5000;
const UNKNOWN_KEY = "\u0000unknown";  // cannot collide with a company name
const FEED_ROWS = 12;

const $ = id => document.getElementById(id);
const state = {
  hits: [], devices: {}, session: null, ended: null, summary: null, label: null,
  blocked: {companies: [], domains: [], covers: {}}, health: {},
  clockOffset: 0,          // browser clock minus backend clock, learned from live hits
  startedLocal: null,      // performance.now() when the running session started, if we saw it start
  sensorSeen: undefined, sensorChangedAt: -1e9,  // the sensor's heartbeat, and when we last saw it move
  shown: null,             // the phone on screen
};
const nodes = new Map();   // company -> bubble
const pending = new Set(); // companies that got a hit since the last frame: pulse them
let dirty = true, awake = 0, undo = null, toastTimer = 0, wipeArmed = 0, fed = new Set();

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function isLoopback(id) { return id.startsWith("127.") || id === "::1"; }  // the box testing itself, not a phone
function plural(n, one, many) { return n + " " + (n === 1 ? one : many || one + "s"); }
function post(path, body) {
  return fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body || {})});
}

// ---------- what to show ----------

// One phone at a time: the session's (running, or the one that just ended), else the phone seen last.
function scope() {
  const s = state.session || state.ended;
  if (s) return {id: s.device_id, from: s.started, to: s.stopped || Infinity, label: s.label, session: s};
  const phones = state.hits.filter(h => !isLoopback(h.device_id));
  const known = Object.keys(state.devices).filter(id => !isLoopback(id));
  const id = phones.length ? phones[phones.length - 1].device_id : (known[known.length - 1] || null);
  return {id, from: 0, to: Infinity, label: null, session: null};
}

function derive() {
  const sc = scope();
  const mine = state.hits.filter(h => h.device_id === sc.id && h.ts >= sc.from && h.ts <= sc.to);
  const seen = mine.filter(h => h.block_reason !== "guard");  // guard lookups are hidden-traffic attempts, counted apart
  const companies = new Map();
  const unknown = new Set();
  for (const hit of seen) {
    if (!hit.company) { unknown.add(hit.domain); continue; }
    let c = companies.get(hit.company);
    if (!c) companies.set(hit.company, c = {key: hit.company, name: hit.company, hits: 0, blocked: 0, by: {}, guess: true});
    c.hits++;
    if (hit.blocked) c.blocked++;
    c.by[hit.category] = (c.by[hit.category] || 0) + 1;
    if (hit.source !== "ai") c.guess = false;
  }
  const list = [...companies.values()];
  for (const c of list) {
    c.category = Object.keys(c.by).sort((a, b) => c.by[b] - c.by[a])[0];  // what it was mostly contacted for
    c.stopped = state.blocked.companies.includes(c.name);
  }
  const bubbles = list.slice();
  if (unknown.size) bubbles.push({key: UNKNOWN_KEY, name: "Not identified", hits: unknown.size, blocked: 0, category: "unknown", unit: "server"});
  const kinds = {};
  for (const b of bubbles) kinds[b.category] = (kinds[b.category] || 0) + (b.key === UNKNOWN_KEY ? b.hits : 1);
  return {
    sc, bubbles, kinds, latest: mine.slice(-FEED_ROWS).reverse(), companies: list.length,
    advertising: kinds.advertising || 0, analytics: kinds.analytics || 0,
    blocked: seen.filter(h => h.blocked).length, hidden: mine.length - seen.length,
  };
}

function seconds() {
  const s = state.session || state.ended;
  if (!s) return null;
  if (s.stopped) return Math.max(0, Math.round(s.stopped - s.started));
  if (state.startedLocal != null) return Math.floor((performance.now() - state.startedLocal) / 1000);
  return Math.max(0, Math.floor(Date.now() / 1000 - state.clockOffset - s.started));
}

// ---------- bubbles: a small physics loop ----------

let box = null;  // the stage's size and where the phone is, measured at each render and resize

function measure() {
  const field = $("stage").getBoundingClientRect();
  const within = rect => ({left: rect.left - field.left, right: rect.right - field.left, top: rect.top - field.top, bottom: rect.bottom - field.top});
  const phone = within($("phone").getBoundingClientRect()), handset = within($("handset").getBoundingClientRect());
  box = {w: field.width, h: field.height, phone, hx: (handset.left + handset.right) / 2, hy: (handset.top + handset.bottom) / 2};
}

function makeNode() {
  const button = el("button", null, "bubble");
  button.type = "button";
  const disc = el("span", null, "disc");
  const tag = el("span", null, "tag"), name = el("span", null, "name"), count = el("span", null, "count");
  disc.append(tag, name, count);
  button.append(disc);
  button.addEventListener("click", () => toggleBlock(button.dataset.company));
  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  $("lines").append(line);
  $("bubbles").append(button);
  // New bubbles come out of the phone, towards the emptier side of the screen.
  let sx = 0, sy = 0;
  for (const other of nodes.values()) { sx += (other.x - box.w / 2) * other.r * other.r; sy += (other.y - box.h / 2) * other.r * other.r; }
  const angle = (sx || sy ? Math.atan2(-sy, -sx) : Math.random() * Math.PI * 2) + (Math.random() - 0.5) * 1.6;
  const reach = Math.hypot(box.phone.right - box.phone.left, box.phone.bottom - box.phone.top) / 2;  // start clear of the phone's labels
  return {el: button, disc, tag, name, count, line, r: 8, target: 8, shown: 0, vx: Math.cos(angle) * 6, vy: Math.sin(angle) * 6,
          x: box.w / 2 + Math.cos(angle) * reach, y: box.h / 2 + Math.sin(angle) * reach};
}

function reconcile(view) {
  measure();
  // Size by number of contacts, then scale all bubbles together so they fill about the same share
  // of the screen whether there are five or eighty.
  const raw = view.bubbles.map(b => 30 + 11 * Math.sqrt(b.hits));
  const area = raw.reduce((sum, r) => sum + Math.PI * r * r, 0) || 1;
  const free = box.w * box.h - (box.phone.right - box.phone.left) * (box.phone.bottom - box.phone.top);
  const scale = Math.min(Math.sqrt(0.41 * free / area), Math.min(box.w, box.h) / 420);
  const keep = new Set();
  view.bubbles.forEach((b, i) => {
    keep.add(b.key);
    let node = nodes.get(b.key);
    if (!node) nodes.set(b.key, node = makeNode());
    const r = node.target = Math.max(16, Math.min(raw[i] * scale, box.h * 0.2));
    const blockable = b.key !== UNKNOWN_KEY;
    const words = b.name.split(/\s+/), longest = Math.max(...words.map(word => word.length));
    node.el.dataset.company = blockable ? b.name : "";
    node.el.disabled = !blockable;
    node.el.className = "bubble" + (b.stopped ? " stopped" : "") + (b.guess ? " guess" : "") +
      (r < 30 ? " tiny" : r < 46 ? " small" : "") + (node.el.classList.contains("pulse") ? " pulse" : "");
    node.disc.className = "disc " + (b.stopped ? "" : b.category);
    node.tag.className = "tag " + b.category;
    node.tag.textContent = TAG[b.category] + (b.guess ? " · AI guess" : "");
    node.name.textContent = b.name;
    node.count.textContent = b.stopped ? "blocked ×" + b.blocked : plural(b.hits, b.unit || "lookup");
    node.el.title = b.name + ": " + b.category + ", " + plural(b.hits, b.unit || "lookup") +
      (blockable ? (b.stopped ? ". Blocked: click to unblock." : ". Click to block.") : "");
    // The name has to fit inside the circle: the longest word sets the limit.
    node.el.style.fontSize = Math.max(8, Math.min(r * 0.3, (1.76 * r - 5) / (0.64 * Math.max(longest, 4)), 28)) + "px";
    node.line.classList.toggle("stopped", !!b.stopped);
  });
  for (const [key, node] of nodes) {
    if (keep.has(key)) continue;
    nodes.delete(key);
    node.line.remove();
    node.el.classList.add("leaving");
    setTimeout(() => node.el.remove(), 450);
  }
  for (const key of pending) {
    const node = nodes.get(key);
    if (!node) continue;
    node.el.classList.remove("pulse");
    void node.el.offsetWidth;  // restart the animation
    node.el.classList.add("pulse");
    node.line.classList.add("flash");
    setTimeout(() => node.line.classList.remove("flash"), 80);
  }
  pending.clear();
  awake = 300;
}

function step() {
  const cx = box.w / 2, cy = box.h / 2, phone = box.phone;
  const list = [...nodes.values()];
  let energy = 0, mx = 0, my = 0, mass = 0;
  for (const a of list) {
    a.r += (a.target - a.r) * 0.16;  // grow and shrink smoothly
    mx += a.x * a.r * a.r; my += a.y * a.r * a.r; mass += a.r * a.r;
  }
  // Pull to the middle, harder vertically: the cloud then takes the wide shape of the screen. And
  // shift the whole cloud so that its centre of mass sits on the phone.
  const ox = mass ? mx / mass - cx : 0, oy = mass ? my / mass - cy : 0, wide = (box.h / box.w) ** 2;
  for (const a of list) {
    a.vx += (cx - a.x) * 0.006 * wide - ox * 0.03;
    a.vy += (cy - a.y) * 0.006 - oy * 0.03;
    // Keep clear of the phone and its labels: a rectangle.
    const nx = Math.min(phone.right, Math.max(phone.left, a.x)), ny = Math.min(phone.bottom, Math.max(phone.top, a.y));
    let dx = a.x - nx, dy = a.y - ny, d = Math.hypot(dx, dy);
    if (d === 0) { dx = a.x - cx || 1; dy = a.y - cy; d = Math.hypot(dx, dy); a.vx += dx / d * 3; a.vy += dy / d * 3; }
    else if (d < a.r + 12) { const gap = a.r + 12 - d; a.vx += dx / d * gap * 0.3; a.vy += dy / d * gap * 0.3; }
  }
  for (let i = 0; i < list.length; i++) {
    for (let j = i + 1; j < list.length; j++) {
      const a = list[i], b = list[j];
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1, overlap = a.r + b.r + 9 - d;
      if (overlap <= 0) continue;
      const push = overlap * 0.24, ux = dx / d, uy = dy / d;
      a.vx -= ux * push; a.vy -= uy * push; b.vx += ux * push; b.vy += uy * push;
    }
  }
  for (const a of list) {
    a.vx *= 0.78; a.vy *= 0.78;
    a.x = Math.min(box.w - a.r - 3, Math.max(a.r + 3, a.x + a.vx));
    a.y = Math.min(box.h - a.r - 3, Math.max(a.r + 3, a.y + a.vy));
    energy += Math.abs(a.vx) + Math.abs(a.vy) + Math.abs(a.target - a.r);
    if (Math.abs(a.shown - a.r) > 0.2) { a.shown = a.r; a.el.style.width = a.el.style.height = 2 * a.r + "px"; }
    a.el.style.transform = "translate3d(" + (a.x - a.r) + "px," + (a.y - a.r) + "px,0)";
    a.line.x1.baseVal.value = box.hx; a.line.y1.baseVal.value = box.hy;
    a.line.x2.baseVal.value = a.x; a.line.y2.baseVal.value = a.y;
  }
  if (energy > 0.15 * list.length) awake = Math.max(awake, 40);
}

// ---------- the rest of the page ----------

function setNumber(id, value) {
  const node = $(id);
  const text = String(value);
  if (node.textContent === text) return;
  node.textContent = text;
  const box = node.parentElement;
  box.classList.remove("bump");
  void box.offsetWidth;
  box.classList.add("bump");
}

function render() {
  const view = derive();
  setNumber("n-companies", view.companies);
  setNumber("n-advertising", view.advertising);
  setNumber("n-analytics", view.analytics);
  setNumber("n-blocked", view.blocked);
  setNumber("n-hidden", view.hidden);

  const sc = view.sc;
  state.shown = sc.id;
  const device = sc.id && state.devices[sc.id];
  $("phone-name").textContent = sc.id ? ((device && device.name) || sc.id) : "";
  $("phone-app").textContent = sc.session ? (sc.label || "session") + (state.session ? "" : " · ended") : "";
  $("hint").textContent = !sc.id ? "Waiting for a phone on Tattle-Demo…" : sc.session ? "" : "S starts a session";
  reconcile(view);  // after the phone's labels: they decide where bubbles may not go
  for (const item of $("legend").children) {
    if (!item.dataset.kind) continue;
    const n = view.kinds[item.dataset.kind] || 0;
    item.classList.toggle("none", n === 0);
    item.lastChild.textContent = n ? String(n) : "";
  }

  const summary = state.summary && state.summary.device_id === sc.id ? state.summary : null;
  $("summary-card").hidden = !summary;
  if (summary) {
    $("summary-text").textContent = summary.text;
    $("summary-by").textContent = summary.by === "template" ? "" : "written by " + summary.by;
  }

  const check = state.label && state.label.label && sc.session ? state.label : null;
  $("label-card").hidden = !check;
  if (check) {
    $("label-app").textContent = String(check.label.app || "");
    $("label-level").textContent = check.level === "mismatch" ? "✕ DOES NOT MATCH" : "✓ CONSISTENT";
    $("label-level").className = "verdict " + (check.level === "mismatch" ? "mismatch" : "consistent");
    $("label-verdict").textContent = check.verdict;
    $("label-facts").textContent = check.verdict_by === "rules" ? "" : check.rule_verdict;
    const tracked = (check.label.data_used_to_track_you || []).map(String);
    const says = el("li");
    says.append(el("b", "The label says: "), check.label.data_not_collected ? "no data collected" :
      "data used to track you: " + (tracked.length ? tracked.slice(0, 4).join(", ") : "none"));
    $("label-claims").replaceChildren(says);
  }

  // The latest names the phone asked for, newest first: the raw material behind the bubbles.
  $("feed-card").hidden = !!check || !view.latest.length;
  const rows = view.latest.map(hit => {
    const hidden = hit.block_reason === "guard";
    const row = el("li", null, (hit.blocked ? "stopped" : "") + (fed.has(hit) ? "" : " new"));
    row.append(el("span", hit.blocked ? "NO" : TAG[hit.category] || "?", "tag " + (hit.blocked ? "" : hit.category)),
               el("span", hidden ? "hidden traffic, refused" : hit.blocked ? "blocked: " + (hit.company || "this name") : hit.company || "not identified", "who"),
               el("span", hit.domain, "host"));
    return row;
  });
  fed = new Set(view.latest);
  $("feed").replaceChildren(...rows);
  $("feed").classList.toggle("clipped", $("feed").scrollHeight > $("feed").clientHeight + 1);  // fade the last row only when rows are cut off

  const select = $("ctl-device");
  const chosen = select.value;
  select.replaceChildren(...Object.values(state.devices).filter(d => !isLoopback(d.device_id)).map(d => {
    const option = el("option", d.name || d.device_id);
    option.value = d.device_id;
    return option;
  }));
  if (state.devices[chosen]) select.value = chosen; else if (sc.id) select.value = sc.id;
  $("ctl-stop").disabled = !state.session;
}

function renderStatus() {
  const s = seconds();
  $("n-seconds").textContent = s == null ? "–" : String(s);
  const live = document.body.classList.contains("offline") === false;
  $("chip-link").textContent = live ? "live" : "reconnecting…";
  $("chip-link").className = "chip " + (live ? "on" : "off");
  const sensor = performance.now() - state.sensorChangedAt < 12000;
  $("chip-sensor").textContent = sensor ? "sensor: live" : "sensor: silent";
  $("chip-sensor").className = "chip " + (sensor ? "on" : "");
  const ai = state.health.ai_endpoint === true || state.health.ai === true;
  $("chip-ai").textContent = ai ? "AI: on" : "AI: off";
  $("chip-ai").className = "chip " + (ai ? "on" : "");
}

function frame() {
  if (dirty) { dirty = false; render(); }
  if (awake > 0) { awake--; step(); }
  requestAnimationFrame(frame);
}

function toast(text, undoAction) {
  undo = undoAction || null;
  $("toast-text").textContent = text;
  $("toast-undo").hidden = !undo;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; undo = null; }, 8000);
}

async function toggleBlock(company) {
  if (!company) return;
  const wasBlocked = state.blocked.companies.includes(company);
  try {
    const response = await post(wasBlocked ? "/api/unblock" : "/api/block", {company});
    if (!response.ok) throw new Error(response.status);
    if (wasBlocked) return toast("Unblocked " + company + ".", () => post("/api/block", {company}));
    const body = await response.json();
    const names = ((body.covers || {})[company] || []).length;
    toast("Blocked " + company + " (" + plural(names, "name") + "). It stops new connections: close the app and open it again.",
          () => post("/api/unblock", {company}));
  } catch (error) {
    toast("That did not work. Is the backend running?");
  }
}

// ---------- operator controls ----------

function open(id) { for (const o of document.querySelectorAll(".overlay")) o.hidden = o.id !== id; }
function closeAll() { for (const o of document.querySelectorAll(".overlay")) o.hidden = true; }

function startSession() {
  const device_id = $("ctl-device").value;
  if (!device_id) return toast("No phone yet: it has to join Tattle-Demo first.");
  post("/api/session/start", {device_id, label: $("ctl-label").value.trim() || null});
  closeAll();
}
function stopSession() { post("/api/session/stop"); closeAll(); }
function wipe() {
  if (performance.now() - wipeArmed > 3000) {  // a wipe needs two presses
    wipeArmed = performance.now();
    $("ctl-wipe").textContent = "Press again to wipe";
    setTimeout(() => { $("ctl-wipe").textContent = "Wipe everything"; }, 3000);
    return toast("Press W again to wipe everything.");
  }
  wipeArmed = 0;
  post("/api/wipe");
  closeAll();
  toast("Wiped. Nothing is kept.");
}

$("open-how").addEventListener("click", () => open("how"));
$("open-controls").addEventListener("click", () => open("controls"));
$("ctl-start").addEventListener("click", startSession);
$("ctl-stop").addEventListener("click", stopSession);
$("ctl-wipe").addEventListener("click", wipe);
$("ctl-label").addEventListener("keydown", event => { if (event.key === "Enter") startSession(); });
$("toast-undo").addEventListener("click", () => { if (undo) undo(); $("toast").hidden = true; undo = null; });
for (const overlay of document.querySelectorAll(".overlay")) {
  overlay.addEventListener("click", event => { if (event.target === overlay || event.target.closest("[data-close]")) closeAll(); });
}
document.addEventListener("keydown", event => {
  if (event.key === "Escape") return closeAll();
  if (event.ctrlKey || event.metaKey || event.altKey || /^(INPUT|SELECT|TEXTAREA)$/.test(event.target.tagName)) return;
  const key = event.key.toLowerCase();
  if (key === "h") $("how").hidden ? open("how") : closeAll();
  else if (key === "c") $("controls").hidden ? open("controls") : closeAll();
  else if (key === "s") {
    if (state.session) return stopSession();
    open("controls");
    event.preventDefault();  // or the "s" lands in the input we are about to focus
    $("ctl-label").focus();
  } else if (key === "w") wipe();
  else if (key === "f") document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen().catch(() => {});
});
window.addEventListener("resize", () => { dirty = true; });
if (document.fonts) document.fonts.ready.then(() => { dirty = true; });  // sizes change once the font is in

// ---------- the live connection ----------

function sawHealth(health) {
  // The sensor is alive while its heartbeat keeps moving. The first value we get may be old: for that one, compare clocks.
  if (health.sensor_seen != null && health.sensor_seen !== state.sensorSeen) {
    const first = state.sensorSeen === undefined;
    if (!first || Math.abs(Date.now() / 1000 - state.clockOffset - health.sensor_seen) < 15) state.sensorChangedAt = performance.now();
  }
  state.sensorSeen = health.sensor_seen;
  state.health = health;
}

// The label check has no push message: ask when a session starts or stops, and every few seconds while one is on screen.
function askLabel() {
  const asked = state.session || state.ended;
  if (!asked) return;
  fetch("/api/label-check").then(response => response.json()).then(body => {
    const now = state.session || state.ended;
    if (now && body.session && body.session.started === now.started) { state.label = body; dirty = true; }  // not an answer about an older session
  }).catch(() => {});
}

const handlers = {
  snapshot(m) {
    state.devices = {};
    for (const d of m.devices) state.devices[d.device_id] = d;
    state.hits = m.hits.slice(-MAX_HITS);
    state.blocked = m.blocked; state.session = m.session; state.summary = m.summary || null;
    state.ended = m.session ? null : (m.last_session || null);
    state.startedLocal = null; state.label = null;
    sawHealth(m.health || {});
    askLabel();
  },
  device(m) { state.devices[m.device_id] = m; },
  hit(m) {
    state.hits.push(m);
    if (state.hits.length > MAX_HITS) state.hits.shift();
    state.clockOffset = Date.now() / 1000 - m.ts;  // a live hit is stamped "now" on the backend's clock
    if (m.device_id === state.shown && m.block_reason !== "guard") pending.add(m.company || UNKNOWN_KEY);  // pulse its bubble
  },
  classified(m) {
    for (const hit of state.hits) {
      if (hit.domain === m.domain && hit.source === "unknown") { hit.company = m.company; hit.category = m.category; hit.source = "ai"; }
    }
  },
  summary(m) { state.summary = m; },
  blocked(m) { state.blocked = m; },
  session(m) {
    if (m.session) {
      state.session = m.session; state.ended = null; state.summary = null; state.label = null; state.startedLocal = performance.now();
      askLabel();
    }
    else if (state.session) {
      state.ended = {...state.session, stopped: state.session.started + seconds()};  // our estimate, until the backend's exact time arrives
      state.session = null;
      fetch("/api/state").then(response => response.json()).then(body => {
        if (body.last_session && state.ended && !state.session) { state.ended = body.last_session; dirty = true; }
      }).catch(() => {});
      askLabel();
    }
  },
  health(m) { sawHealth(m); },
  wiped() {
    state.hits = []; state.devices = {}; state.session = null; state.ended = null; state.summary = null; state.label = null;
  },
};

function connect() {
  const socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  socket.onopen = () => document.body.classList.remove("offline");
  socket.onmessage = event => {
    let message;
    try { message = JSON.parse(event.data); } catch (error) { return; }
    const handler = handlers[message.type];
    if (!handler) return;  // a message type this page does not know: ignore it
    handler(message);
    dirty = true;
  };
  socket.onclose = () => { document.body.classList.add("offline"); setTimeout(connect, 1000); };
}

setInterval(askLabel, 4000);
setInterval(renderStatus, 250);

$("legend").replaceChildren(
  ...CATEGORIES.map(c => {
    const item = el("li", null, "none");
    item.dataset.kind = c.id;
    item.append(el("span", c.tag, "tag " + c.id), c.label, el("b"));
    return item;
  }),
  el("li", "Click a company to block it. Grey and dashed: blocked.", "how"));
renderStatus();
requestAnimationFrame(frame);
connect();
