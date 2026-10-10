"use strict";
// Tattle show screen: the phone in the middle, one bubble per company it contacts.
// Everything that comes from the API (names, companies, sentences) is put on the page with
// textContent, never as markup: a phone chooses the names it looks up.

// `kind` completes "<company>: <kind>, according to our tracker list." The same words as KINDS in
// backend/app/explain.py: the detail panel opens with this sentence before the backend has answered.
const CATEGORIES = [
  {id: "advertising", tag: "AD", label: "advertising", kind: "an advertising company"},
  {id: "analytics", tag: "AN", label: "analytics", kind: "an analytics company: it measures how an app is used"},
  {id: "social", tag: "SO", label: "social", kind: "a social network"},
  {id: "fingerprinting", tag: "FP", label: "fingerprinting", kind: "a company known for fingerprinting: telling devices apart by their technical traits"},
  {id: "content", tag: "CDN", label: "content delivery", kind: "a content delivery company: it serves files such as images and video for other companies"},
  {id: "vendor", tag: "OWN", label: "the phone's or app's own", kind: "the phone maker's or the app's own servers"},
  {id: "unknown", tag: "?", label: "not identified yet", kind: "a company we have no category for"},
];
const TAG = Object.fromEntries(CATEGORIES.map(c => [c.id, c.tag]));
const BY_ID = Object.fromEntries(CATEGORIES.map(c => [c.id, c]));
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
  detail: null,            // the company whose detail panel is open (UNKNOWN_KEY for "Not identified")
};
const nodes = new Map();   // company -> bubble
const pending = new Set(); // companies that got a hit since the last frame: pulse them
const explained = new Map();  // company -> the backend's last answer to /api/explain: opening it again is instant
const rowNodes = new Map();   // server name -> its row in the detail panel
let dirty = true, awake = 0, toastTimer = 0, wipeArmed = 0, fed = new Set();
let explainTurn = 0, explainTimer = 0, detailNote = null;

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
  const alone = new Map();  // server name -> blocked on its own? (only worked out when single names are blocked)
  const single = name => {
    if (!state.blocked.domains.length) return false;
    if (!alone.has(name)) alone.set(name, !!coveredBy(name));
    return alone.get(name);
  };
  let unknownPartly = false;
  for (const hit of seen) {
    if (!hit.company) { unknown.add(hit.domain); unknownPartly = unknownPartly || single(hit.domain); continue; }
    let c = companies.get(hit.company);
    if (!c) companies.set(hit.company, c = {key: hit.company, name: hit.company, hits: 0, blocked: 0, by: {}, guess: true, partly: false});
    c.hits++;
    c.partly = c.partly || single(hit.domain);
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
  if (unknown.size) bubbles.push({key: UNKNOWN_KEY, name: "Not identified", hits: unknown.size, blocked: 0, category: "unknown", unit: "server", partly: unknownPartly});
  const kinds = {};
  for (const b of bubbles) kinds[b.category] = (kinds[b.category] || 0) + (b.key === UNKNOWN_KEY ? b.hits : 1);
  return {
    sc, seen, bubbles, kinds, latest: mine.slice(-FEED_ROWS).reverse(), companies: list.length,
    advertising: kinds.advertising || 0, analytics: kinds.analytics || 0,
    blocked: seen.filter(h => h.blocked).length, hidden: mine.length - seen.length,
  };
}

// The single blocked name that covers this server name (itself or a parent), if there is one.
function coveredBy(name) {
  return state.blocked.domains.find(d => name === d || name.endsWith("." + d)) || null;
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
  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  $("lines").append(line);
  $("bubbles").append(button);
  // New bubbles come out of the phone, towards the emptier side of the screen.
  let sx = 0, sy = 0;
  for (const other of nodes.values()) { sx += (other.x - box.w / 2) * other.r * other.r; sy += (other.y - box.h / 2) * other.r * other.r; }
  const angle = (sx || sy ? Math.atan2(-sy, -sx) : Math.random() * Math.PI * 2) + (Math.random() - 0.5) * 1.6;
  const reach = Math.hypot(box.phone.right - box.phone.left, box.phone.bottom - box.phone.top) / 2;  // start clear of the phone's labels
  const node = {el: button, disc, tag, name, count, line, r: 8, target: 8, shown: 0, vx: Math.cos(angle) * 6, vy: Math.sin(angle) * 6,
                x: box.w / 2 + Math.cos(angle) * reach, y: box.h / 2 + Math.sin(angle) * reach};
  button.addEventListener("click", () => openDetail(node.key));
  return node;
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
    const words = b.name.split(/\s+/), longest = Math.max(...words.map(word => word.length));
    node.key = b.key;
    node.el.className = "bubble" + (b.stopped ? " stopped" : b.partly ? " partly" : "") + (b.guess ? " guess" : "") +
      (r < 30 ? " tiny" : r < 46 ? " small" : "") + (node.el.classList.contains("pulse") ? " pulse" : "");
    node.disc.className = "disc " + (b.stopped ? "" : b.category);
    node.tag.className = "tag " + b.category;
    node.tag.textContent = TAG[b.category] + (b.guess ? " · AI guess" : "");
    node.name.textContent = b.name;
    node.count.textContent = b.stopped ? "blocked ×" + b.blocked : plural(b.hits, b.unit || "lookup");
    node.el.title = b.name + ": " + b.category + ", " + plural(b.hits, b.unit || "lookup") +
      (b.stopped ? ". Blocked." : b.partly ? ". Some of its names are blocked." : "") + " Click for details.";
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
  renderDetail(view);
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
  for (const node of rowNodes.values()) node.last.textContent = ago(node.ts);  // "last seen" keeps counting between lookups
}

function frame() {
  if (dirty) { dirty = false; render(); }
  if (awake > 0) { awake--; step(); }
  requestAnimationFrame(frame);
}

function toast(text) {
  $("toast-text").textContent = text;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 8000);
}

// ---------- the detail panel: one company, every server name, blocking ----------

function ago(ts) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - state.clockOffset - ts));
  return s < 2 ? "just now" : s < 90 ? s + " s ago" : s < 5400 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago";
}

function listSentence(b) {
  return b.name + ": " + (BY_ID[b.category] || BY_ID.unknown).kind +
    (b.guess ? ", according to the AI's guess. It is not on our tracker list." : ", according to our tracker list.");
}

// The backend answers at once with the tracker list's sentence and asks the AI in the background:
// while it says "pending" and the panel is still on this company, ask again.
function askExplain(company) {
  const turn = ++explainTurn;
  clearTimeout(explainTimer);
  const phone = state.shown ? "&device_id=" + encodeURIComponent(state.shown) : "";
  fetch("/api/explain?company=" + encodeURIComponent(company) + phone).then(response => response.ok ? response.json() : null).then(body => {
    if (!body) return;
    explained.set(company, body);
    dirty = true;
    if (body.pending && turn === explainTurn && state.detail === company) explainTimer = setTimeout(() => askExplain(company), 1200);
  }).catch(() => {});
}

function openDetail(key) {
  open("detail");
  state.detail = key;
  detailNote = null;
  rowNodes.clear();
  $("detail-rows").replaceChildren();
  if (key !== UNKNOWN_KEY) askExplain(key);
  dirty = true;
}

function leaveDetail() { state.detail = null; explainTurn++; clearTimeout(explainTimer); }

function makeRow(name) {
  // A long name is cut short in its front part: the last two labels say whose server it is, so they
  // always stay. The full name is the tooltip.
  const li = el("li"), who = el("span", null, "who"), host = el("span", null, "host");
  const cut = name.lastIndexOf(".", name.lastIndexOf(".") - 1);
  host.append(el("span", name.slice(0, cut + 1), "front"), el("span", name.slice(cut + 1), "owner"));
  const node = {li, tag: el("span", null, "tag"), guess: el("span", null, "guess"), count: el("span", null, "n"),
                last: el("span", null, "last"), now: el("span", null, "now"), button: el("button", null, "act"), ts: 0};
  host.title = name;
  node.button.type = "button";
  node.button.dataset.domain = name;
  who.append(host, node.guess);
  li.append(node.tag, who, node.count, node.last, node.now, node.button);
  return node;
}

function renderDetail(view) {
  const key = state.detail;
  if (!key) return;
  const bubble = view.bubbles.find(b => b.key === key);
  if (!bubble) return closeAll();  // wiped, a new session, or the AI put a company to the last unknown name
  const unknown = key === UNKNOWN_KEY, whole = !unknown && state.blocked.companies.includes(key);

  // Every server name of this company, most looked up first.
  const rows = new Map();
  for (const hit of view.seen) {
    if ((hit.company || UNKNOWN_KEY) !== key) continue;
    let row = rows.get(hit.domain);
    if (!row) rows.set(hit.domain, row = {name: hit.domain, count: 0, refused: 0, last: 0});
    row.count++;
    if (hit.blocked) row.refused++;
    if (hit.ts >= row.last) { row.last = hit.ts; row.category = hit.category; row.guess = hit.source === "ai"; }
  }
  const list = [...rows.values()].sort((a, b) => b.count - a.count || b.last - a.last || (a.name < b.name ? -1 : 1));
  let stoppedNames = 0;
  for (const row of list) {
    let node = rowNodes.get(row.name);
    if (!node) rowNodes.set(row.name, node = makeRow(row.name));
    const stopped = whole || !!coveredBy(row.name);
    if (stopped) stoppedNames++;
    node.ts = row.last;
    node.li.className = stopped ? "stopped" : "";
    node.tag.className = "tag " + row.category;
    node.tag.textContent = TAG[row.category] || "?";
    node.guess.textContent = row.guess ? "AI guess: " + (unknown ? "" : key + ", ") + (BY_ID[row.category] || BY_ID.unknown).label :
      unknown ? "no AI guess" : "";
    node.count.textContent = String(row.count);
    node.last.textContent = ago(row.last);
    node.now.textContent = stopped ? "BLOCKED" + (row.refused ? " · refused ×" + row.refused : "") :
      row.refused ? "refused ×" + row.refused + " earlier" : "open";
    node.button.textContent = stopped ? "Unblock" : "Block";
    node.button.className = "act" + (stopped ? " undo" : "");
    node.button.hidden = whole;  // one name cannot be let through while its whole company is blocked
  }
  for (const [name, node] of rowNodes) {
    if (!rows.has(name)) { node.li.remove(); rowNodes.delete(name); }
  }
  // Keep the order still while the pointer is on the list, or a button could move away under a click.
  const box = $("detail-rows"), wanted = list.map(row => rowNodes.get(row.name).li);
  if (!box.matches(":hover") && wanted.some((li, i) => box.children[i] !== li)) box.replaceChildren(...wanted);
  else for (const li of wanted) if (!li.parentNode) box.append(li);

  $("detail-tag").className = "tag " + bubble.category;
  $("detail-tag").textContent = TAG[bubble.category] + (bubble.guess ? " · AI guess" : "");
  $("detail-name").textContent = bubble.name;
  $("detail-kind").textContent = (unknown ? "" : (BY_ID[bubble.category] || BY_ID.unknown).label + " · ") +
    plural(list.length, "server name") + " · " + plural(list.reduce((sum, row) => sum + row.count, 0), "lookup");

  const answer = unknown ? null : explained.get(key), byAi = !!answer && answer.by !== "list";
  // The list's sentence is built here, from the bubble as it is now: the backend's copy dates from
  // when the panel asked, and a company's category can change as more lookups arrive.
  $("detail-text").textContent = !unknown ? (byAi ? answer.text : listSentence(bubble)) : "No list knows these server names. " + (state.health.ai === true ?
    "The AI is asked about each one in the background: a name it can put a company to moves to that company's bubble, marked as a guess." :
    "No AI is answering right now, so they stay unidentified.");  // health.ai: the last call to the AI module worked
  $("detail-facts").textContent = byAi ? listSentence(bubble) : "";
  $("detail-by").textContent = unknown ? "NOT IDENTIFIED" : byAi ? "FROM THE AI" : bubble.guess ? "AI GUESS, NOT ON OUR LIST" : "FROM OUR TRACKER LIST";
  $("detail-by").className = "source" + (byAi ? " ai" : "");
  $("detail-model").textContent = byAi && answer.by !== "ai" ? "written by " + answer.by : "";
  $("detail-thinking").hidden = !(answer && answer.pending);

  const covered = whole ? ((state.blocked.covers || {})[key] || []).length : 0;
  $("detail-state").textContent = whole ? "BLOCKED" : stoppedNames ? stoppedNames + " OF " + list.length + " BLOCKED" : "NOT BLOCKED";
  $("detail-state").className = "state" + (whole ? " blocked" : stoppedNames ? " partly" : "");
  $("detail-note").textContent = detailNote || (
    whole ? "Every lookup of " + key + " is refused (" + plural(covered, "name") + " on our list). A block stops new connections: close the app and open it again." :
    stoppedNames ? "Blocked names are refused. A block stops new connections: close the app and open it again." :
    unknown ? "These names have no company, so each one is blocked on its own." : "Block the whole company here, or single server names below.");
  $("detail-block").hidden = unknown;
  $("detail-block").textContent = (whole ? "Unblock " : "Block ") + bubble.name;
  $("detail-block").className = "act" + (whole ? " undo" : "");
}

async function setBlock(target, on) {
  try {
    const response = await post(on ? "/api/block" : "/api/unblock", target);
    if (!response.ok) throw new Error(response.status);
    state.blocked = await response.json();  // the same message also arrives on the WebSocket
    detailNote = null;
  } catch (error) {
    detailNote = "That did not work. Is the backend running?";
  }
  dirty = true;
}

$("detail-block").addEventListener("click", () => {
  const key = state.detail;
  if (key && key !== UNKNOWN_KEY) setBlock({company: key}, !state.blocked.companies.includes(key));
});
$("detail-rows").addEventListener("click", event => {
  const button = event.target.closest("button");
  if (!button) return;
  const cover = coveredBy(button.dataset.domain);
  setBlock({domain: cover || button.dataset.domain}, !cover);
});

// ---------- operator controls ----------

function open(id) {
  if (id !== "detail") leaveDetail();
  for (const o of document.querySelectorAll(".overlay")) o.hidden = o.id !== id;
}
function closeAll() {
  leaveDetail();
  for (const o of document.querySelectorAll(".overlay")) o.hidden = true;
}

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
    $("ctl-label").select();  // the last session's app name is marked, so typing replaces it
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
    explained.clear();  // the backend may have restarted: ask again
    if (state.detail && state.detail !== UNKNOWN_KEY) askExplain(state.detail);
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
      explained.clear();  // an explanation is about what one session contacted
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
    explained.clear();
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
  el("li", "Click a company for details and blocking. Grey and dashed: blocked.", "how"));

// The browser-tab icon is the header's logo: one drawing, used twice.
const icon = el("link");
icon.rel = "icon";
icon.type = "image/svg+xml";
icon.href = "data:image/svg+xml," + encodeURIComponent(new XMLSerializer().serializeToString($("logo")));
document.head.append(icon);

renderStatus();
requestAnimationFrame(frame);
connect();
