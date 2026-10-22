"use strict";

// Shorthand for finding an element by its id.
const $ = (id) => document.getElementById(id);
const STATUS_LABELS = { "proposed": "PROPOSED", "question": "NEEDS YOUR ANSWER", "unable": "COULD NOT SCHEDULE" };
const ZONES = { "America/New_York": "New York", "Europe/London": "London", "America/Denver": "Denver", "Asia/Singapore": "Singapore" };
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const state = {
  world: null, zone: "America/New_York",
  people: {}, rooms: {},          // id -> person / room, from /api/world
  focus: null,                    // person ids in the current request (null = everyone)
  hold: null,                     // the pencilled-in hold while the AI works
  sent: [], deadlines: {},        // the outbox, and when each Undo runs out (browser clock)
  inkId: null, lastInked: null,   // the send that should "ink in" on the next draw
  sampleId: null, lastRequest: "", running: false, gotResult: false,
  proposal: null, acting: false,
};

// Ask the browser each time we need it, so a changed setting is respected mid-session.
const prefersReducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- theme ---------- */
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  $("theme-icon").textContent = theme === "dark" ? "☀" : "☾";
  try { localStorage.setItem("theme", theme); } catch (e) { /* private mode: just don't remember */ }
}
$("theme-toggle").addEventListener("click", () =>
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
$("theme-icon").textContent = document.documentElement.dataset.theme === "dark" ? "☀" : "☾";

/* ---------- small helpers ---------- */
// Build an element. Text goes in via textContent, so it can never be read as HTML.
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} -> ${response.status}`);
  return response.json();
}
function postJson(url, body) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body });
}
function showNotice(message) {
  // Unhide first, then set the text, so screen readers announce the change.
  $("notice").hidden = false;
  $("notice").textContent = message;
}
function announce(message) { $("announce").textContent = message; }
const isText = (value) => typeof value === "string" && value.length > 0;
const firstName = (id) => (state.people[id] ? state.people[id].name.split(" ")[0] : String(id));
const roomName = (id) => (state.rooms[id] ? state.rooms[id].name : String(id || "a room"));
function joinNames(ids) {
  const names = ids.map(firstName);
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
// The label in a busy block: one letter when that is enough to tell the people shown apart.
function shortLabels(ids) {
  const firsts = ids.map((id) => state.people[id].name.slice(0, 1).toUpperCase());
  const unique = new Set(firsts).size === firsts.length;
  return Object.fromEntries(ids.map((id, i) => [id, unique && ids.length > 4 ? firsts[i] : initials(state.people[id].name)]));
}
function initials(name) {
  const words = String(name).split(" ").filter(Boolean);
  return words.length > 1 ? words[0][0] + words[words.length - 1][0] : String(name).slice(0, 2);
}

/* ---------- time zones (display only: every real time is computed on the server) ---------- */
const formats = {};
// One cached Intl.DateTimeFormat per zone and style; making them is slow.
function fmt(zone, kind) {
  const key = `${zone}|${kind}`;
  if (!formats[key]) {
    const options = kind === "parts"
      ? { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }
      : kind === "clock" ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }
        : { weekday: "short", day: "numeric", month: "short" };
    formats[key] = new Intl.DateTimeFormat("en-GB", { timeZone: zone, ...options });
  }
  return formats[key];
}
// A moment (milliseconds) as a date "YYYY-MM-DD" and minutes after midnight, in `zone`.
function wallClock(ms, zone) {
  const p = {};
  for (const part of fmt(zone, "parts").formatToParts(new Date(ms))) p[part.type] = part.value;
  return { date: `${p.year}-${p.month}-${p.day}`, minutes: (Number(p.hour) % 24) * 60 + Number(p.minute) };
}
const clock = (ms, zone) => fmt(zone, "clock").format(new Date(ms));
const dayLabel = (ms, zone) => fmt(zone, "day").format(new Date(ms));
function addDays(date, n) {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}
// The moment when the clocks in `zone` read `hhmm` on `date`.
function zoneMoment(date, hhmm, zone) {
  const [y, m, d] = date.split("-").map(Number);
  const [h, mi] = hhmm.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, d, h, mi);
  const offset = (ms) => {
    const w = wallClock(ms, zone);
    const [wy, wm, wd] = w.date.split("-").map(Number);
    return Date.UTC(wy, wm - 1, wd) + w.minutes * 60000 - Math.floor(ms / 60000) * 60000;
  };
  const first = guess - offset(guess);
  return guess - offset(first);  // a second pass settles the offset near a clock change
}
function parseUtc(text) {
  const ms = typeof text === "string" ? Date.parse(text) : NaN;
  return Number.isFinite(ms) ? ms : null;
}
// Cut [start, end) into pieces that each sit on one day in `zone`: {date, from, to} in minutes.
function piecesIn(start, end, zone) {
  const pieces = [];
  let at = start;
  for (let guard = 0; at < end && guard < 4; guard += 1) {
    const w = wallClock(at, zone);
    const midnight = zoneMoment(addDays(w.date, 1), "00:00", zone);
    const stop = Math.min(end, midnight);
    pieces.push({ date: w.date, from: w.minutes, to: stop === midnight ? 1440 : wallClock(stop, zone).minutes });
    at = stop;
  }
  return pieces;
}
const weekDates = () => [0, 1, 2, 3, 4].map((n) => addDays(state.world.week.monday, n));

/* ---------- loading the world, the samples and the outbox ---------- */
async function init() {
  const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  state.zone = ZONES[browserZone] ? browserZone : "America/New_York";
  $("zone").value = state.zone;
  try {
    const world = await getJson("/api/world");
    if (!world || !world.week || !isText(world.week.monday) || !Array.isArray(world.people)) throw new Error("bad world");
    state.world = world;
    for (const person of world.people) if (person && isText(person.id)) state.people[person.id] = person;
    for (const room of Array.isArray(world.rooms) ? world.rooms : []) if (room && isText(room.id)) state.rooms[room.id] = room;
    renderWeek();
  } catch (error) {
    showNotice("Could not load the calendars. Refresh to try again.");
  }
  try {
    const samples = await getJson("/api/samples");
    for (const sample of Array.isArray(samples) ? samples : []) {
      if (!sample || !isText(sample.label) || !isText(sample.request)) continue;
      const chip = el("button", "sample", sample.label);
      chip.type = "button";
      chip.setAttribute("aria-pressed", "false");
      chip.addEventListener("click", () => chooseSample(sample, chip));
      $("samples").append(chip);
    }
    if (!$("samples").children.length) $("samples").append(el("p", "hint", "No recorded samples yet. Type your own request above."));
  } catch (error) {
    $("samples").append(el("p", "hint", "Could not load the sample requests. Type your own above."));
  }
  try {
    setOutbox((await getJson("/api/outbox")).sent);
  } catch (error) { /* an empty outbox is the right default */ }
}
function chooseSample(sample, chip) {
  $("request").value = sample.request;
  state.sampleId = isText(sample.id) ? sample.id : null;  // lets replay mode find the recording
  for (const other of $("samples").querySelectorAll(".sample")) {
    other.setAttribute("aria-pressed", String(other === chip));
  }
  $("request").focus();
}
// Editing the request means it no longer matches a recording, so forget the sample.
$("request").addEventListener("input", () => {
  state.sampleId = null;
  for (const chip of $("samples").querySelectorAll(".sample")) chip.setAttribute("aria-pressed", "false");
});
$("zone").addEventListener("change", () => {
  state.zone = ZONES[$("zone").value] ? $("zone").value : "America/New_York";
  renderWeek();
  renderOutbox();
});

/* ---------- the week grid ---------- */
function shownPeople() {
  const all = Object.keys(state.people);
  const focus = (state.focus || []).filter((id) => state.people[id]);
  return focus.length ? focus : all;
}
// Working hours as pieces in the chosen zone, for each of the week's days.
function workPieces(person, zone, dates) {
  const hours = Array.isArray(person.working_hours) ? person.working_hours : [];
  const days = Array.isArray(person.working_days) ? person.working_days : [];
  if (!isText(hours[0]) || !isText(hours[1])) return [];
  const pieces = [];
  // Look one day either side: Singapore's Monday morning is still Sunday evening in New York.
  for (let n = -1; n <= 5; n += 1) {
    const date = addDays(dates[0], n);
    const [y, m, d] = date.split("-").map(Number);
    if (!days.includes(WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()])) continue;
    const start = zoneMoment(date, hours[0], person.time_zone);
    const end = zoneMoment(date, hours[1], person.time_zone);
    pieces.push(...piecesIn(start, end, zone).filter((p) => dates.includes(p.date)));
  }
  return pieces;
}
// Put a block at the right height, using CSS custom properties (the CSP allows no inline styles).
function place(node, piece, firstHour) {
  node.style.setProperty("--from", String(piece.from / 60 - firstHour));
  node.style.setProperty("--len", String((piece.to - piece.from) / 60));
}
function blockText(kind, start, end, zone) {
  return `${kind}, ${clock(start, zone)} to ${clock(end, zone)}`;
}

function renderWeek() {
  if (!state.world) return;
  const zone = state.zone;
  const dates = weekDates();
  const people = shownPeople();
  const work = Object.fromEntries(people.map((id) => [id, workPieces(state.people[id], zone, dates)]));
  const labels = shortLabels(people);

  // The pencilled-in hold, and meetings already approved and sent.
  const marks = [];
  for (const mark of [...(state.hold ? [{ kind: "hold", ...state.hold }] : []), ...state.sent.map((s) => ({ kind: "booked", ...s }))]) {
    const start = parseUtc(mark.start_utc);
    const end = parseUtc(mark.end_utc);
    if (start !== null && end !== null) marks.push({ ...mark, start, end, pieces: piecesIn(start, end, zone) });
  }

  // Show the hours anyone shown is at work (and any hold or booking); past midnight, the whole day.
  const all = [...Object.values(work).flat(), ...marks.flatMap((m) => m.pieces.filter((p) => dates.includes(p.date)))];
  let firstHour = all.length ? Math.floor(Math.min(...all.map((p) => p.from)) / 60) : 8;
  let lastHour = all.length ? Math.ceil(Math.max(...all.map((p) => p.to)) / 60) : 18;
  if (lastHour - firstHour < 8) {  // never squeeze the grid below eight hours
    lastHour = Math.min(24, firstHour + 8);
    firstHour = Math.max(0, lastHour - 8);
  }
  const hours = lastHour - firstHour;
  const grid = $("week-grid");
  grid.style.setProperty("--hours", String(hours));
  grid.style.setProperty("--hour", hours <= 12 ? "2.6rem" : hours <= 16 ? "2.1rem" : "1.55rem");
  grid.style.setProperty("--lanes", String(people.length));
  grid.style.setProperty("--day-min", `${Math.max(6.5, people.length * 1.25)}rem`);

  const city = ZONES[zone];
  const first = zoneMoment(dates[0], "12:00", zone);
  const last = zoneMoment(dates[4], "12:00", zone);
  grid.setAttribute("aria-label", `Busy times from ${dayLabel(first, zone)} to ${dayLabel(last, zone)}, in ${city} time`);
  $("week-who").textContent = state.focus && state.focus.length
    ? `Showing ${joinNames(people)}, the people in this request, in ${city} time.`
    : `Showing everyone’s busy times in ${city} time.`;

  const head = el("div", "grid-row grid-head");
  head.setAttribute("role", "row");
  const corner = el("div", "corner", city);
  corner.setAttribute("role", "columnheader");
  head.append(corner);
  for (const date of dates) {
    const cell = el("div", "col-head");
    cell.setAttribute("role", "columnheader");
    const noon = zoneMoment(date, "12:00", zone);
    const [weekday, ...rest] = dayLabel(noon, zone).split(" ");
    cell.append(el("span", "weekday", weekday.replace(",", "")), el("span", "date", rest.join(" ")));
    head.append(cell);
  }

  const body = el("div", "grid-row");
  body.setAttribute("role", "row");
  const ruler = el("div", "ruler");
  ruler.setAttribute("role", "rowheader");
  ruler.append(el("span", "visually-hidden", `Hours ${String(firstHour).padStart(2, "0")}:00 to ${String(lastHour).padStart(2, "0")}:00`));
  const step = hours > 16 ? 2 : 1;
  for (let h = firstHour; h < lastHour; h += step) {
    const tick = el("span", h === firstHour ? "tick first" : "tick", `${String(h).padStart(2, "0")}:00`);
    tick.setAttribute("aria-hidden", "true");
    tick.style.setProperty("--at", String(h - firstHour));
    ruler.append(tick);
  }
  body.append(ruler);

  const visible = (piece) => piece.to / 60 > firstHour && piece.from / 60 < lastHour;
  const clip = (piece) => ({ ...piece, from: Math.max(piece.from, firstHour * 60), to: Math.min(piece.to, lastHour * 60) });
  for (const date of dates) {
    const cell = el("div", "day");
    cell.setAttribute("role", "cell");
    // The lanes are decoration: the list below carries the same facts in words.
    const lanes = el("div", "lanes");
    lanes.setAttribute("aria-hidden", "true");
    const items = [];
    people.forEach((id, lane) => {
      const column = el("div", "lane");
      for (const piece of work[id].filter((p) => p.date === date && visible(p))) {
        const band = el("div", "at-work");
        place(band, clip(piece), firstHour);
        column.append(band);
      }
      lanes.append(column);
      const busy = Array.isArray(state.world.busy[id]) ? state.world.busy[id] : [];
      for (const block of busy) {
        const start = parseUtc(block && block.start_utc);
        const end = parseUtc(block && block.end_utc);
        if (start === null || end === null) continue;
        for (const piece of piecesIn(start, end, zone).filter((p) => p.date === date && visible(p))) {
          const name = state.people[id].name;
          const item = el("li", "block busy");
          item.style.setProperty("--lane", String(lane));
          place(item, clip(piece), firstHour);
          item.title = blockText(`${name} busy`, start, end, zone);
          const label = el("span", "block-label", labels[id]);
          label.setAttribute("aria-hidden", "true");
          item.append(label, el("span", "visually-hidden", blockText(`${name} busy`, start, end, zone)));
          items.push({ start, item });
        }
      }
    });
    for (const mark of marks) {
      const { start, end } = mark;
      for (const piece of mark.pieces.filter((p) => p.date === date && visible(p))) {
        const item = el("li", `block ${mark.kind}`);
        place(item, clip(piece), firstHour);
        const room = mark.kind === "hold" ? roomName(mark.room_id) : (mark.room && mark.room.name) || "";
        const words = mark.kind === "hold" ? `Pencilled in, not sent: ${room}` : `Booked: ${room}`;
        item.title = blockText(words, start, end, zone);
        const label = el("span", "block-label", mark.kind === "hold" ? `Pencilled in: ${room}` : `Booked: ${room}`);
        label.setAttribute("aria-hidden", "true");
        item.append(label, el("span", "visually-hidden", blockText(words, start, end, zone)));
        if (mark.kind === "booked" && mark.send_id === state.inkId) item.classList.add("ink-in");
        items.push({ start, item });
      }
    }
    const list = el("ul", "day-list");
    list.setAttribute("aria-label", "Busy times");
    list.append(...items.sort((a, b) => a.start - b.start).map((entry) => entry.item));
    if (!items.length) list.append(el("li", "visually-hidden", "Nothing busy"));
    cell.append(lanes, list);
    body.append(cell);
  }
  grid.replaceChildren(head, body);
  state.inkId = null;  // the ink-in plays once, not again on the next redraw
  renderLegend(people, labels);
}
function renderLegend(people, labels) {
  $("legend").replaceChildren(...people.map((id) => {
    const person = state.people[id];
    const item = el("li");
    const badge = el("span", "initials", labels[id]);
    badge.setAttribute("aria-hidden", "true");
    const hours = Array.isArray(person.working_hours) ? person.working_hours.join("–") : "";
    item.append(badge, el("span", "who-name", person.name),
      el("span", "who-zone", `${ZONES[person.time_zone] || person.time_zone}, works ${hours} local`));
    return item;
  }));
}
// Narrow the grid to the people named in a tool call or result.
function focusOn(ids) {
  const known = (Array.isArray(ids) ? ids : []).filter((id) => typeof id === "string" && state.people[id]);
  if (!known.length) return;
  state.focus = known;
  renderWeek();
}

/* ---------- making a request ---------- */
function resetResults() {
  $("trail").replaceChildren();
  $("log-empty").hidden = true;
  for (const id of ["notice", "proposal", "question-card", "unable-card", "preview"]) $(id).hidden = true;
  announce("");
  state.gotResult = false;
  state.proposal = null;
  state.hold = null;
}
function setRunning(running) {
  state.running = running;
  // aria-disabled (not disabled) keeps keyboard focus on the button while it works.
  $("schedule").setAttribute("aria-disabled", String(running));
  $("reply").setAttribute("aria-disabled", String(running));
  $("schedule").textContent = running ? "Finding a time…" : "Find a time";
}

async function schedule(request, clarification) {
  if (state.running) return;
  state.lastRequest = request;
  setRunning(true);
  resetResults();
  state.focus = null;
  renderWeek();
  try {
    const response = await fetch("/schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, clarification, sample_id: state.sampleId }),
    });
    if (!response.ok) {
      showNotice(response.status === 429
        ? "That was a lot of requests in a short time. Wait a minute and try again."
        : response.status === 422
          ? "The front desk could not take that request. Check it is not empty and is under 500 characters."
          : `The server could not take that request (${response.status}).`);
      return;
    }
    if (!response.body) {  // some browsers/proxies give no readable stream
      showNotice("Your browser could not read the steps as they streamed. Please try again.");
      return;
    }
    await readEventStream(response.body, handleEvent);
    // The stream closed cleanly but never produced a result: say so instead of staying silent.
    if (!state.gotResult && $("notice").hidden) showNotice("The run ended without a result. Please try again.");
  } catch (error) {
    showNotice("Could not reach the server. Please try again.");
  } finally {
    // A line still waiting now never got its result.
    for (const line of $("trail").querySelectorAll(".step.pending")) {
      line.classList.replace("pending", state.gotResult ? "done" : "error");
      if (!state.gotResult) line.querySelector(".step-result").textContent = "Stopped";
    }
    setRunning(false);
    // No proposal or question to read: put focus back on the request button.
    if (!state.gotResult || (!state.proposal && $("question-card").hidden)) $("schedule").focus();
  }
}
$("request-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const request = $("request").value.trim();
  if (!request) {
    showNotice("Type a request first, or pick one of the samples.");
    $("request").focus();
    return;
  }
  schedule(request, null);
});
// Answering a question sends the original request again, with the answer attached.
$("reply-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const clarification = $("clarification").value.trim();
  if (!clarification) { $("clarification").focus(); return; }
  if (state.lastRequest) schedule(state.lastRequest, clarification);
});

// Server-Sent Events arrive as text blocks like  "data: {...}\n\n"; split and parse them.
async function readEventStream(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let end;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      handleFrame(frame, onEvent);
    }
  }
  // A last frame with no blank line after it still counts.
  buffer += decoder.decode().replace(/\r\n/g, "\n");
  if (buffer.trim()) handleFrame(buffer.trim(), onEvent);
}
// One frame: "data: {...}" (the space after the colon is optional in SSE).
function handleFrame(frame, onEvent) {
  if (!frame.startsWith("data:")) return;
  let parsed;
  try {
    parsed = JSON.parse(frame.slice(5).replace(/^ /, ""));
  } catch (e) {
    return;  // a garbled frame should not kill the whole stream
  }
  onEvent(parsed);
}

// One bad event must not end the run or look like a network failure.
function handleEvent(event) {
  try {
    routeEvent(event);
  } catch (error) {
    showNotice("Part of this run could not be shown. The rest of the log is still here.");
  }
}
function routeEvent(event) {
  if (!event || typeof event !== "object") return;
  if (event.type === "notice") showNotice(String(event.message || ""));
  else if (event.type === "tool_call") addStep(event);
  else if (event.type === "tool_result") finishStep(event);
  else if (event.type === "result") showResult(event.result || {}, event);
}

/* ---------- the desk log: one line per tool call ---------- */
function describeCall(name, input) {
  const people = Array.isArray(input.people) ? input.people : [];
  if (name === "list_people") return "Looked up who works here";
  if (name === "list_rooms") return "Looked over the rooms";
  if (name === "get_busy_times") return `Read the calendars of ${joinNames(people) || "the people involved"}`;
  if (name === "find_open_slots") {
    const minutes = Number.isFinite(input.duration_minutes) ? `${input.duration_minutes}-minute ` : "";
    return `Asked code for open ${minutes}times for ${joinNames(people) || "the people involved"}`;
  }
  if (name === "place_hold") {
    const start = parseUtc(input.start_utc);
    const when = start === null ? "a time" : `${dayLabel(start, state.zone)} ${clock(start, state.zone)} (${ZONES[state.zone]})`;
    return `Pencilling in ${when} in ${roomName(input.room_id)}`;
  }
  if (name === "release_hold") return "Rubbed out a pencilled-in time";
  if (name === "submit_proposal") return "Wrote up the proposal for you";
  if (name === "ask_question") return "Wrote a question for you";
  return `Used ${name}`;
}
function addStep(event) {
  const input = event.input && typeof event.input === "object" ? event.input : {};
  if (["get_busy_times", "find_open_slots", "place_hold"].includes(event.name)) focusOn(input.people);
  const line = el("li", "step pending");
  line.append(el("span", "step-what", describeCall(String(event.name || ""), input)), el("span", "step-result"));
  if (isText(event.id)) line.dataset.callId = event.id;
  $("trail").append(line);
}
function finishStep(event) {
  const out = event.output && typeof event.output === "object" ? event.output : {};
  if (!isText(event.id)) return;
  const line = $("trail").querySelector(`[data-call-id="${CSS.escape(event.id)}"]`);
  if (!line) return;
  const result = line.querySelector(".step-result");
  line.classList.remove("pending");
  if (out.error) {
    line.classList.add("error");
    const sentBack = event.name === "submit_proposal" || event.name === "ask_question";
    result.textContent = `${sentBack ? "Code sent it back" : "Code refused"}: ${String(out.error)}`;
    return;
  }
  line.classList.add("done");
  if (event.name === "list_people") result.textContent = `${(out.people || []).length} people`;
  else if (event.name === "list_rooms") result.textContent = `${(out.rooms || []).length} rooms`;
  else if (event.name === "get_busy_times") {
    const blocks = Object.values(out.busy || {}).reduce((n, list) => n + (Array.isArray(list) ? list.length : 0), 0);
    result.textContent = `${blocks} busy block${blocks === 1 ? "" : "s"}`;
  } else if (event.name === "find_open_slots") {
    const slots = Array.isArray(out.slots) ? out.slots.length : 0;
    result.textContent = slots ? `Found ${slots} open time${slots === 1 ? "" : "s"}` : "No open times";
  } else if (event.name === "place_hold") {
    result.textContent = "Pencilled in. Nothing sent.";
    if (isText(out.start_utc) && isText(out.end_utc)) {
      state.hold = { hold_id: out.hold_id, start_utc: out.start_utc, end_utc: out.end_utc, room_id: out.room_id };
      if (Array.isArray(out.people)) focusOn(out.people); else renderWeek();
    }
  } else if (event.name === "release_hold") {
    result.textContent = "Rubbed out";
    if (state.hold && state.hold.hold_id === out.hold_id) { state.hold = null; renderWeek(); }
  } else {
    result.textContent = "Done";
  }
}

/* ---------- the result ---------- */
// "Used 4 model calls, 10,937 tokens, 7.3 seconds". Each piece is checked and simply
// left out when it is missing.
function usageText(event) {
  const parts = [];
  if (Number.isInteger(event.turns)) parts.push(`${event.turns} model call${event.turns === 1 ? "" : "s"}`);
  const u = event.usage || {};
  if (Number.isFinite(u.input_tokens) && Number.isFinite(u.output_tokens)) {
    parts.push(`${(u.input_tokens + u.output_tokens).toLocaleString("en-US")} tokens`);
  }
  if (Number.isFinite(event.elapsed_seconds)) parts.push(`${event.elapsed_seconds.toFixed(1)} seconds`);
  return parts.length ? `Used ${parts.join(", ")}` : "";
}
function textList(value) {
  return (Array.isArray(value) ? value : []).filter(isText);
}

function showResult(result, event) {
  state.gotResult = true;
  const status = STATUS_LABELS[result.status] ? result.status : "unable";
  for (const line of $("trail").querySelectorAll(".step.pending")) line.classList.replace("pending", "done");
  for (const line of $("trail").querySelectorAll(".step.done .step-result")) if (!line.textContent) line.textContent = "Done";

  if (status === "proposed" && isText(result.proposal_id)) {
    showProposal(result, event);
  } else if (status === "question") {
    state.hold = null;  // asking a question releases the holds
    renderWeek();
    $("question-stamp").textContent = STATUS_LABELS.question;
    $("question-text").textContent = isText(result.question) ? result.question : "Could you say a little more?";
    $("question-usage").textContent = usageText(event);
    $("clarification").value = "";
    $("question-card").hidden = false;
    announce(`${STATUS_LABELS.question}. ${$("question-text").textContent}`);
    $("question-card").focus();
  } else {
    state.hold = null;
    renderWeek();
    $("unable-stamp").textContent = STATUS_LABELS.unable;
    $("unable-reason").textContent = isText(result.reason) ? result.reason : "The front desk could not find a time for this one.";
    $("unable-usage").textContent = usageText(event);
    $("unable-card").hidden = false;
    announce(`${STATUS_LABELS.unable}. ${$("unable-reason").textContent}`);
  }
}

function showProposal(result, event) {
  state.proposal = { id: result.proposal_id };
  // Draw the proposal's own slot as the hold (it is the one the AI kept).
  if (isText(result.start_utc) && isText(result.end_utc)) {
    state.hold = { hold_id: result.hold_id, start_utc: result.start_utc, end_utc: result.end_utc,
      room_id: result.room && result.room.id };
  }
  const attendees = (Array.isArray(result.attendees) ? result.attendees : []).filter((a) => a && isText(a.name));
  state.focus = attendees.map((a) => a.id).filter((id) => state.people[id]);
  renderWeek();

  // Times and room: every value here was computed by code on the server.
  const rows = el("ul");
  for (const person of attendees) {
    const row = el("li", "time-row");
    const when = isText(person.local_start) && isText(person.local_end) ? `${person.local_start}–${person.local_end}` : "";
    row.append(el("span", "time-name", person.name), el("span", "time-when", when),
      el("span", "time-zone", ZONES[person.time_zone] ? `${ZONES[person.time_zone]} time` : String(person.time_zone || "")));
    rows.append(row);
  }
  const minutes = Number.isFinite(result.duration_minutes) ? `, ${result.duration_minutes} minutes` : "";
  const room = result.room && isText(result.room.name) ? result.room.name : "No room given";
  $("proposal-times").replaceChildren(rows, el("p", "room-line", `Room: ${room}${minutes}`));

  // Claude's note: the model's own words, shown as its note, not as facts.
  $("note-summary").textContent = isText(result.summary) ? result.summary : "";
  const reasons = textList(result.reasons);
  const tradeoffs = textList(result.tradeoffs);
  $("note-reasons").replaceChildren(...reasons.map((text) => el("li", "", text)));
  $("note-tradeoffs").replaceChildren(...tradeoffs.map((text) => el("li", "", text)));
  $("note-tradeoffs-block").hidden = tradeoffs.length === 0;

  $("proposal-status").textContent = STATUS_LABELS.proposed;
  $("usage").textContent = usageText(event);
  $("proposal-actions").hidden = false;
  $("proposal-outcome").hidden = true;
  $("preview").hidden = true;
  setActing(false);
  $("proposal").hidden = false;
  announce(`${STATUS_LABELS.proposed}: ${attendees.length} people in ${room}. Nothing is sent until you approve.`);
  $("proposal").scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "nearest" });
  $("proposal").focus({ preventScroll: true });
}

/* ---------- Approve, Reject, Dry run: the browser sends only the proposal's id ---------- */
function setActing(acting) {
  state.acting = acting;
  for (const id of ["approve", "reject", "dry-run"]) $(id).setAttribute("aria-disabled", String(acting));
}
function endProposal(message) {
  state.proposal = null;
  $("proposal-actions").hidden = true;
  $("proposal-outcome").hidden = false;
  $("proposal-outcome").textContent = message;
}
function refusalText(status, data) {
  if (status === 429) return "That was a lot of requests in a short time. Wait a minute and try again.";
  if (status === 404) return "This proposal is no longer on file (visits reset after 30 minutes). Make the request again.";
  if (status === 409 && data && isText(data.detail)) return data.detail;
  return `The server could not do that (${status}).`;
}

async function decide(path) {
  if (!state.proposal || state.acting) return;
  setActing(true);
  let ended = false;
  try {
    const response = await postJson(path, JSON.stringify({ proposal_id: state.proposal.id }));
    let data = {};
    try { data = await response.json(); } catch (e) { /* no body: handled by status below */ }
    if (!response.ok) {
      const message = refusalText(response.status, data);
      if (response.status === 404) { endProposal(message); ended = true; $("schedule").focus(); }
      else showNotice(message);
      announce(message);
      return;
    }
    if (path === "/approve") {
      state.hold = null;
      state.inkId = data.sent && data.sent.send_id;
      setOutbox(data.outbox);
      endProposal("Approved. Plain code checked the slot was still free, then sent the invites and booked the room.");
      ended = true;
      announce("Approved and sent. The meeting is in your outbox, and you can undo it for 10 minutes.");
      const item = $("outbox").querySelector(`[data-send-id="${CSS.escape(String(state.lastInked || ""))}"]`);
      (item || $("outbox-heading")).focus();
    } else if (path === "/reject") {
      state.hold = null;
      renderWeek();
      endProposal("Rejected. Nothing was sent, and the pencilled-in time is rubbed out.");
      ended = true;
      announce("Rejected. Nothing was sent.");
      $("schedule").focus();
    } else {
      showPreview(data);
    }
  } catch (error) {
    showNotice("Could not reach the server. Please try again.");
  } finally {
    if (!ended) setActing(false);
  }
}
$("approve").addEventListener("click", () => decide("/approve"));
$("reject").addEventListener("click", () => decide("/reject"));
$("dry-run").addEventListener("click", () => decide("/dry-run"));

function showPreview(data) {
  const preview = $("preview");
  const invites = (Array.isArray(data.invites) ? data.invites : []).filter((i) => i && isText(i.to));
  const free = data.still_free === true;
  const room = data.room && isText(data.room.name) ? data.room.name : "the room";
  const list = el("ul");
  for (const invite of invites) list.append(el("li", "", `To ${invite.to}: ${isText(invite.when) ? invite.when : ""}`));
  list.append(el("li", "", `Book ${room}`));
  preview.replaceChildren(
    el("h4", "", "Dry run: nothing was sent"),
    el("p", "", free ? "Everyone and the room are still free, so Approve would send these:"
      : "Someone or the room is no longer free, so Approve would be refused. It would have sent:"),
    list);
  preview.hidden = false;
  announce(`Dry run. Nothing was sent. ${invites.length} invites and one room booking would go out.${free ? "" : " The slot is no longer free."}`);
}

/* ---------- the outbox, with Undo ---------- */
function setOutbox(sent) {
  const list = (Array.isArray(sent) ? sent : []).filter((s) => s && isText(s.send_id));
  const now = Date.now();
  state.deadlines = {};
  for (const send of list) {
    const left = Number.isFinite(send.undo_seconds_left) ? send.undo_seconds_left : 0;
    state.deadlines[send.send_id] = now + left * 1000;
  }
  state.lastInked = state.inkId;
  state.sent = list;
  renderWeek();
  renderOutbox();
}
function secondsLeft(sendId) {
  return Math.max(0, Math.ceil(((state.deadlines[sendId] || 0) - Date.now()) / 1000));
}
function leftText(seconds) {
  if (seconds <= 0) return "Too late to undo";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} left to undo`;
}
function renderOutbox() {
  $("outbox-empty").hidden = state.sent.length > 0;
  $("outbox").replaceChildren(...state.sent.map((send) => {
    const item = el("li", "sent");
    item.tabIndex = -1;
    item.dataset.sendId = send.send_id;
    const start = parseUtc(send.start_utc);
    const end = parseUtc(send.end_utc);
    const when = start !== null && end !== null
      ? `${dayLabel(start, state.zone)}, ${clock(start, state.zone)}–${clock(end, state.zone)} ${ZONES[state.zone]} time` : "";
    const room = send.room && isText(send.room.name) ? ` in ${send.room.name}` : "";
    const names = (Array.isArray(send.invites) ? send.invites : []).map((i) => i && i.to).filter(isText);
    const what = el("div", "sent-what");
    what.append(el("span", "sent-when", `${when}${room}`), el("span", "sent-who", `Invites sent to ${names.join(", ")}`));
    const undo = el("div", "sent-undo");
    const button = el("button", "quiet-btn", "Undo");
    button.type = "button";
    const left = el("span", "undo-left", leftText(secondsLeft(send.send_id)));
    left.id = `left-${send.send_id}`;
    button.setAttribute("aria-describedby", left.id);
    button.setAttribute("aria-label", `Undo the meeting ${when}${room}`);
    button.addEventListener("click", () => undoSend(send.send_id, button));
    undo.append(button, left);
    item.append(what, undo);
    return item;
  }));
  tick();
}
// Once a second: count down, and switch Undo off when its time is up.
function tick() {
  for (const item of $("outbox").querySelectorAll(".sent")) {
    const seconds = secondsLeft(item.dataset.sendId);
    item.querySelector(".undo-left").textContent = leftText(seconds);
    if (seconds <= 0) item.querySelector("button").setAttribute("aria-disabled", "true");
  }
}
setInterval(tick, 1000);

async function undoSend(sendId, button) {
  if (button.getAttribute("aria-disabled") === "true") return;
  button.setAttribute("aria-disabled", "true");
  try {
    const response = await postJson("/undo", JSON.stringify({ send_id: sendId }));
    let data = {};
    try { data = await response.json(); } catch (e) { /* handled by status below */ }
    if (!response.ok) {
      const message = refusalText(response.status, data);
      showNotice(message);
      announce(message);
      if (secondsLeft(sendId) > 0 && response.status !== 409) button.setAttribute("aria-disabled", "false");
      return;
    }
    setOutbox(data.outbox);
    announce("Undone. The invites are cancelled and the slot is free again.");
    const next = $("outbox").querySelector(".sent");
    (next || $("schedule")).focus();
  } catch (error) {
    showNotice("Could not reach the server. Please try again.");
    button.setAttribute("aria-disabled", "false");
  }
}

init();
