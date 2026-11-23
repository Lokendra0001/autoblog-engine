"""Local test page: type a keyword, generate an article, view it. No publishing.

Binds to 127.0.0.1 only by default, so it is reachable from this computer alone.
"""

from __future__ import annotations

import html
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import config, pipeline, planner, publisher, strapi

_STYLES = """
:root {
  --stone: #f8fafc;
  --paper: #ffffff;
  --line: #e2e8f0;
  --line-2: #cbd5e1;
  --ink: #0f172a;
  --heading: var(--navy);
  --ink-2: #334155;
  --muted: #64748b;

  /* Brand palette from bhandaritechfab.com */
  --navy: #071938;
  --blue: #014ca9;
  --blue-2: #013d88;
  --blue-soft: #eef4fc;
  --gold: #f4b41a;
  --gold-2: #cd9716;

  --pine: var(--blue);
  --pine-2: var(--blue-2);
  --pine-line: #e2e8f0;
  --pine-text: #94a3b8;

  --orange: var(--gold);
  --orange-2: var(--gold-2);

  --ok: #15803d;    --ok-bg: #f0fdf4;
  --warn: #b45309;  --warn-bg: #fffbeb;
  --bad: #b91c1c;   --bad-bg: #fef2f2;
  --idle: #475569;  --idle-bg: #f1f5f9;

  --display: 'Cabinet Grotesk', 'DM Sans', sans-serif;
  --sans: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --gutter: clamp(16px, 2.6vw, 44px);
}

* { box-sizing: border-box; margin: 0; padding: 0; border-radius: 0; }
body {
  font-family: var(--sans);
  font-size: 14px;
  line-height: 1.5;
  color: var(--ink);
  background: #ffffff;
  -webkit-font-smoothing: antialiased;
  -webkit-text-size-adjust: 100%;
}
a { color: inherit; text-decoration: none; }
.container { max-width: 1900px; margin: 0 auto; padding: 0 var(--gutter); }
.mono { font-family: var(--mono); }

/* ── Header band (navy, as on bhandaritechfab.com) ─────────── */
.band { background: var(--navy); color: #fff; border-top: 4px solid var(--blue); }
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  height: 54px;
  border-bottom: 1px solid rgba(255, 255, 255, .12);
  font-size: 13px;
}
.logo { display: flex; align-items: center; gap: 10px; letter-spacing: -0.01em; color: #fff; font-family: var(--display); font-size: 16px; font-weight: 800; }
.logo-mark { display: grid; grid-template-columns: repeat(2, 7px); gap: 2px; }
.logo-mark i { width: 7px; height: 7px; background: #fff; }
.logo-mark i:nth-child(2) { background: #3d7ce0; }
.logo-mark i:last-child { background: var(--gold); }
.bar-meta { display: flex; align-items: center; gap: 24px; color: #9fb0cc; font-size: 12px; }
.bar-meta .live { display: inline-flex; align-items: center; gap: 8px; color: #fff; font-weight: 500; }
.bar-meta .live::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #34d399; }

.hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px 40px;
  padding: 32px 0 26px;
}
.kicker {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--gold);
}
.hero h1 {
  font-family: var(--display);
  font-size: clamp(28px, 3.2vw, 44px);
  font-weight: 800;
  letter-spacing: -0.02em;
  line-height: 1.15;
  margin-top: 6px;
  color: #fff;
}
.hero p { max-width: 520px; color: #b4c2da; font-size: 13.5px; line-height: 1.55; }

.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-top: 1px solid rgba(255, 255, 255, .12);
}
.stat { padding: 18px 24px 22px; border-left: 1px solid rgba(255, 255, 255, .12); }
.stat:first-child { border-left: 0; padding-left: 0; }
.stat-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: #9fb0cc;
}
.stat-value {
  font-family: var(--display);
  font-size: 34px;
  font-weight: 700;
  line-height: 1.1;
  margin-top: 6px;
  color: #fff;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
}
.stat-value small { font-size: 14px; color: #9fb0cc; margin-left: 4px; font-weight: 400; }
.stat-value.text { font-size: 20px; padding-top: 6px; font-weight: 700; }
.stat-note { font-size: 12px; color: #9fb0cc; margin-top: 4px; }
.stat-value.alert-on { color: var(--gold); }
.meter { display: grid; grid-template-columns: repeat(var(--n, 1), 1fr); gap: 3px; margin-top: 10px; max-width: 220px; }
.meter i { height: 4px; background: rgba(255, 255, 255, .16); }
.meter i.on { background: var(--gold); }

/* ── Layout ──────────────────────────────────────────────── */
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 24px;
  padding: 28px 0 72px;
  align-items: start;
}
.grid > * { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: 24px; }
@media (min-width: 1180px) { .grid { grid-template-columns: 400px minmax(0, 1fr); } }
@media (min-width: 1600px) { .grid { grid-template-columns: 460px minmax(0, 1fr); } }

.panel { background: var(--paper); border: 1px solid var(--line); }
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 0 20px;
  height: 52px;
  border-bottom: 1px solid var(--line);
}
.panel-head h2 { font-family: var(--display); font-size: 16px; font-weight: 700; color: var(--heading); }
.panel-head h2::before {
  content: "";
  display: inline-block;
  width: 8px; height: 8px;
  background: var(--orange);
  margin-right: 10px;
  vertical-align: 1px;
}
.panel-head .meta { font-family: var(--mono); font-size: 12px; color: var(--muted); white-space: nowrap; }
.panel-body { padding: 20px; }

/* ── Form ────────────────────────────────────────────────── */
.lede { color: var(--ink-2); margin-bottom: 20px; }
.field { margin-bottom: 18px; }
.field label {
  display: block;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 8px;
}
.input {
  width: 100%;
  height: 48px;
  padding: 0 14px;
  font: inherit;
  font-size: 15px;
  color: var(--ink);
  background: #fff;
  border: 1px solid var(--line-2);
  transition: border-color .12s, box-shadow .12s;
}
.input::placeholder { color: #a39c8d; }
.input:hover { border-color: var(--ink-2); }
.input:focus { outline: none; border-color: var(--blue); box-shadow: 0 0 0 3px rgba(1, 76, 169, .14); }
.hint { font-size: 12px; color: var(--muted); margin-top: 8px; }

.check {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  margin-bottom: 18px;
  background: var(--stone);
  border: 1px solid var(--line);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}
.check input {
  appearance: none;
  flex: none;
  width: 18px; height: 18px;
  margin-top: 1px;
  border: 1.5px solid var(--ink-2);
  background: #fff;
  display: grid; place-content: center;
  cursor: pointer;
}
.check input:checked { background: var(--pine); border-color: var(--pine); }
.check input:checked::after {
  content: "";
  width: 9px; height: 5px;
  border: solid #fff;
  border-width: 0 0 2px 2px;
  transform: translateY(-1px) rotate(-45deg);
}
.check input:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.check small { display: block; font-weight: 400; color: var(--muted); font-size: 12px; margin-top: 2px; }

.btn {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  height: 50px;
  padding: 0 18px;
  font: inherit;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  background: var(--blue);
  border: 0;
  cursor: pointer;
  transition: background .12s;
}
.btn:hover:not(:disabled) { background: var(--navy); }
.btn:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
.btn:disabled { background: var(--muted); cursor: progress; }
.btn svg { transition: transform .15s; }
.btn:hover:not(:disabled) svg { transform: translateX(3px); }

/* ── Automatic publishing (scheduler setting) ────────────── */
.auto { border-top: 3px solid var(--blue); }
.auto-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 18px 32px;
  align-items: center;
  padding: 20px;
}
.auto-lede { color: var(--ink-2); }
.auto-state { font-family: var(--display); font-size: 24px; font-weight: 800; color: var(--heading); margin-top: 4px; line-height: 1.2; }
.auto-state em { font-style: normal; color: var(--blue); }
.auto-state em.live { color: var(--ok); }
.auto-next { font-size: 13px; color: var(--muted); margin-top: 6px; }
.auto-next b { color: var(--ink-2); font-weight: 500; }
.seg { display: grid; grid-template-columns: repeat(2, minmax(150px, 1fr)); border: 1px solid var(--line-2); }
.seg button {
  height: 60px; padding: 0 18px; border: 0; background: #fff; text-align: left;
  font: inherit; font-size: 14px; font-weight: 600; color: var(--ink-2); cursor: pointer;
  transition: background .12s, color .12s;
}
.seg button + button { border-left: 1px solid var(--line-2); }
.seg button small { display: block; font-size: 11.5px; font-weight: 400; color: var(--muted); }
.seg button:hover { background: var(--stone); }
.seg button.on { background: var(--blue); color: #fff; cursor: default; }
.seg button.on.live { background: var(--ok); }
.seg button.on small { color: rgba(255, 255, 255, .8); }
.seg button:focus-visible { outline: 2px solid var(--gold); outline-offset: -2px; }
.auto-note {
  grid-column: 1 / -1;
  display: flex; flex-wrap: wrap; gap: 6px 18px;
  padding-top: 14px; border-top: 1px solid var(--line);
  font-size: 12px; color: var(--muted);
}
.auto-note code { font-family: var(--mono); font-size: 11px; background: var(--stone); padding: 1px 5px; border: 1px solid var(--line); }
@media (max-width: 720px) {
  .auto-body { grid-template-columns: minmax(0, 1fr); padding: 16px; }
  .seg { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .auto-state { font-size: 20px; }
}

/* ── Calendar CMS actions ───────────────────────────────── */
.cms { display: flex; align-items: center; gap: 10px; white-space: nowrap; }
.cms form { margin: 0; }
.btn-pub {
  height: 30px; padding: 0 12px; border: 0;
  background: var(--blue); color: #fff;
  font: inherit; font-size: 12px; font-weight: 600; cursor: pointer;
}
.btn-pub:hover { background: var(--navy); }
.btn-pub:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
.cms-link { font-family: var(--sans); font-size: 12px; color: var(--blue); text-decoration: underline; text-underline-offset: 3px; }
.cms-live { display: inline-flex; align-items: center; gap: 6px; font-family: var(--sans); font-size: 12px; font-weight: 600; color: var(--ok); }
.cms-live::before { content: ""; width: 7px; height: 7px; background: var(--ok); }
.cms-draft { font-family: var(--sans); font-size: 12px; font-weight: 600; color: var(--warn); }

/* ── Publish mode choice ─────────────────────────────────── */
.choice { border: 0; margin-bottom: 18px; }
.choice legend {
  font-family: var(--mono); font-size: 11px; letter-spacing: .1em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 8px;
}
.choice-opts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border: 1px solid var(--line-2); }
.choice-opts label { position: relative; cursor: pointer; }
.choice-opts label + label { border-left: 1px solid var(--line-2); }
.choice-opts input { position: absolute; opacity: 0; pointer-events: none; }
.choice-opts span {
  display: block; padding: 10px 12px; text-align: center;
  font-size: 13px; font-weight: 600; color: var(--ink-2); background: #fff;
  transition: background .12s, color .12s;
}
.choice-opts span small { display: block; font-size: 11px; font-weight: 400; color: var(--muted); margin-top: 1px; }
.choice-opts label:hover span { background: var(--stone); }
.choice-opts input:checked + span { background: var(--blue); color: #fff; }
.choice-opts input:checked + span small { color: #d6e4f7; }
.choice-opts input:focus-visible + span { outline: 2px solid var(--gold); outline-offset: -2px; }
.choice .hint code { font-family: var(--mono); font-size: 11px; background: var(--stone); padding: 1px 5px; border: 1px solid var(--line); }

/* ── Alert ───────────────────────────────────────────────── */
.alert {
  display: flex;
  gap: 14px;
  align-items: baseline;
  margin-top: 28px;
  padding: 14px 18px;
  background: var(--bad-bg);
  border: 1px solid #e9c2b8;
  border-left: 4px solid var(--bad);
  color: #5c1a0f;
}
.alert b { font-family: var(--mono); font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--bad); }

/* ── Recent drafts (Editorial Minimalist List) ───────────── */
.recent { list-style: none; }
.recent li { border-bottom: 1px solid var(--line); }
.recent li:last-child { border-bottom: 0; }
.recent a {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 20px;
  background: #ffffff;
  transition: background .12s ease;
  text-decoration: none;
}
.recent a:hover { background: #f8fafc; }
.recent-left {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.recent-name {
  font-size: 13.5px;
  font-weight: 550;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.recent a:hover .recent-name { color: var(--blue); }
.recent-when {
  font-size: 11.5px;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 8px;
}
.recent-pill {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  background: var(--stone);
  color: var(--ink-2);
  border: 1px solid var(--line);
  border-radius: 3px;
  flex-shrink: 0;
}

.empty { padding: 36px 20px; color: var(--muted); }

/* ── Calendar table ──────────────────────────────────────── */
.table-wrap { overflow-x: auto; }
table.calendar { width: 100%; border-collapse: collapse; text-align: left; }
.calendar th {
  padding: 10px 20px;
  background: var(--stone);
  border-bottom: 1px solid var(--line);
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 400;
  letter-spacing: .1em;
  text-transform: uppercase;
  color: var(--muted);
  white-space: nowrap;
}
.calendar td { padding: 15px 20px; border-bottom: 1px solid var(--line); vertical-align: middle; }
.calendar tbody tr:last-child td { border-bottom: 0; }
.calendar tbody tr:hover td { background: #fff; }
.calendar tr.is-today td { background: var(--blue-soft); }
.calendar tr.is-today td:first-child { box-shadow: inset 4px 0 0 var(--blue); }
.c-date { white-space: nowrap; font-family: var(--mono); }
.c-date b { display: block; font-weight: 500; font-size: 13px; }
.c-date small { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
.is-today .c-date small { color: var(--blue); font-weight: 600; }
.c-title { font-weight: 500; }
.c-title a { color: var(--blue); text-decoration: underline; text-decoration-color: #b9cdea; text-underline-offset: 4px; }
.c-title a:hover { text-decoration-color: var(--pine); }
.c-error { font-size: 12px; color: var(--bad); margin-top: 3px; }
.c-cat { white-space: nowrap; }
.tag { font-size: 12px; color: var(--ink-2); padding: 3px 8px; border: 1px solid var(--line-2); background: #fff; }
.c-cms { font-family: var(--mono); font-size: 12px; color: var(--muted); white-space: nowrap; }

.status {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 24px;
  padding: 0 9px 0 0;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
}
.status::before { content: ""; width: 4px; align-self: stretch; background: currentColor; margin-right: 2px; }
.status-done    { color: var(--ok);   background: var(--ok-bg); }
.status-planned { color: var(--idle); background: var(--idle-bg); }
.status-skipped { color: var(--warn); background: var(--warn-bg); }
.status-failed  { color: var(--bad);  background: var(--bad-bg); }

/* ── Job page ────────────────────────────────────────────── */
.job-grid { padding-top: 28px; padding-bottom: 72px; }
.job { max-width: 760px; }
.progress { position: relative; height: 4px; background: var(--pine-line); overflow: hidden; }
.progress::after {
  content: ""; position: absolute; top: 0; bottom: 0; left: 0; width: 30%;
  background: var(--orange);
  animation: sweep 1.4s cubic-bezier(.6, 0, .4, 1) infinite;
}
@keyframes sweep { from { transform: translateX(-100%); } to { transform: translateX(340%); } }
.steps { list-style: none; counter-reset: s; }
.steps li {
  counter-increment: s;
  display: grid;
  grid-template-columns: 34px 1fr;
  gap: 14px;
  padding: 16px 20px;
}
.steps li + li { border-top: 1px solid var(--line); }
.steps li::before {
  content: counter(s, decimal-leading-zero);
  height: 26px;
  display: grid; place-items: center;
  font-family: var(--mono); font-size: 12px;
  border: 1px solid var(--line-2);
  color: var(--muted);
}
.steps li:first-child::before { background: var(--pine); border-color: var(--pine); color: #fff; }
.steps b { display: block; font-weight: 500; }
.steps span { font-size: 13px; color: var(--muted); }
.job-foot {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px;
  padding: 14px 20px;
  border-top: 1px solid var(--line);
  background: var(--stone);
  font-family: var(--mono); font-size: 12px; color: var(--muted);
}
.btn-line {
  display: inline-flex; align-items: center; gap: 8px;
  height: 36px; padding: 0 14px;
  border: 1px solid var(--ink-2);
  font-family: var(--sans); font-size: 13px; font-weight: 500; color: var(--ink);
  background: var(--paper);
}
.btn-line:hover { background: var(--ink); color: #fff; }

/* ── Responsive ──────────────────────────────────────────── */
@media (max-width: 1000px) {
  .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .stat:nth-child(3) { border-left: 0; padding-left: 0; }
  .stat:nth-child(n+3) { border-top: 1px solid rgba(255, 255, 255, .12); }
}
@media (max-width: 720px) {
  .bar-meta .date { display: none; }
  .hero { padding: 24px 0 20px; }
  .hero p { font-size: 13px; }
  .stat { padding: 14px 14px 16px; }
  .stat-value { font-size: 26px; }
  .stat-value.text { font-size: 18px; padding-top: 4px; }
  .grid { gap: 16px; padding: 16px 0 48px; }
  .grid > * { gap: 16px; }
  .panel-head { padding: 0 16px; height: 48px; }
  .panel-body { padding: 16px; }
  .recent a { padding: 12px 16px; }
  .input { font-size: 16px; }  /* stops iOS zoom on focus */

  /* Calendar rows become stacked blocks */
  .calendar thead { display: none; }
  .calendar, .calendar tbody, .calendar td { display: block; }
  .calendar tr {
    display: grid;
    grid-template-columns: 1fr auto;
    grid-template-areas: "date status" "title title" "meta cms";
    gap: 8px 12px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--line);
  }
  .calendar tbody tr:last-child { border-bottom: 0; }
  .calendar td { padding: 0; border: 0; background: none !important; box-shadow: none !important; }
  .calendar tr.is-today { background: var(--blue-soft); box-shadow: inset 4px 0 0 var(--blue); }
  .calendar .c-date { grid-area: date; }
  .calendar .c-date b, .calendar .c-date small { display: inline; }
  .calendar .c-date small::before { content: " / "; color: var(--line-2); }
  .calendar .c-status { grid-area: status; }
  .calendar .c-topic { grid-area: title; }
  .calendar .c-cat { grid-area: meta; }
  .calendar .c-cms { grid-area: cms; justify-self: end; }
  .job-grid { padding-top: 16px; padding-bottom: 48px; }
  .m-hide { display: none; }
  .steps li { padding: 14px 16px; }
  .job-foot { padding: 12px 16px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
"""

_COMMON_HEAD = f"""
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#071938">
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%23071938'/%3E%3Crect x='7' y='7' width='8' height='8' fill='%23ffffff'/%3E%3Crect x='17' y='7' width='8' height='8' fill='%233d7ce0'/%3E%3Crect x='7' y='17' width='8' height='8' fill='%23ffffff'/%3E%3Crect x='17' y='17' width='8' height='8' fill='%23f4b41a'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&display=swap" rel="stylesheet">
<link href="https://api.fontshare.com/v2/css?f[]=cabinet-grotesk@500,700,800&display=swap" rel="stylesheet">
<style>
{_STYLES}
</style>
"""

_ARROW = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
          'stroke-width="2" stroke-linecap="square" aria-hidden="true"><path d="M4 12h15M13 6l6 6-6 6"/></svg>')
_BACK = ('<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
         'stroke-width="2" stroke-linecap="square" aria-hidden="true"><path d="M20 12H5M11 6l-6 6 6 6"/></svg>')


def _draft_label(stem: str) -> tuple[str, str]:
    """'20261121-1730-gfrp-rebar-cost' -> ('Gfrp rebar cost', '21 Nov 2026 · 17:30'); other names pass through."""
    try:
        when = datetime.strptime(stem[:13], "%Y%m%d-%H%M").strftime("%d %b %Y · %H:%M")
        slug = stem[14:]
    except ValueError:
        return stem, ""
    return (slug.replace("-", " ").capitalize() or stem), when


def _bar(today: str, dest_label: str) -> str:
    return f"""
    <div class="bar">
      <a class="logo" href="/"><span class="logo-mark"><i></i><i></i><i></i><i></i></span>AutoBlog</a>
      <div class="bar-meta">
        <span class="date">{today}</span>
        <span class="live">{dest_label}</span>
      </div>
    </div>"""


def _dest_label(destination: str, cms_status: str) -> str:
    return f"{destination} / {cms_status}" if cms_status else "Local files"


def _render_job_page(client_name: str, today: str, keyword: str, started: str,
                     destination: str, cms_status: str, uploading: bool) -> str:
    upload_step = (
        f'<li><div><b>{"Publish on" if cms_status == "published" else "Upload to"} {destination}</b>'
        f'<span>{"Goes live on the website." if cms_status == "published" else "Saved as a draft for review in the CMS."}</span></div></li>'
        if uploading else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
{_COMMON_HEAD}
<meta http-equiv="refresh" content="5">
<title>Writing: {keyword} · AutoBlog</title>
</head>
<body>
<header class="band">
  <div class="container">
    {_bar(today, _dest_label(destination, cms_status))}
    <div class="hero">
      <div>
        <p class="kicker">{client_name} · Writing article</p>
        <h1>{keyword}</h1>
      </div>
      <p>Researching and writing now. This page refreshes every 5 seconds and opens the article when it is ready.</p>
    </div>
  </div>
  <div class="progress" role="progressbar" aria-label="Generating article"></div>
</header>
<main class="container job-grid" aria-live="polite">
  <section class="panel job">
    <div class="panel-head"><h2>Pipeline</h2><span class="meta">Started {started}</span></div>
    <ol class="steps">
      <li><div><b>Research</b><span>Gathers sources and facts on the topic.</span></div></li>
      <li><div><b>Write and review</b><span>Drafts the article and revises it, up to three passes.</span></div></li>
      <li><div><b>Save draft</b><span>Stored locally so you can preview it here.</span></div></li>
      {upload_step}
    </ol>
    <div class="job-foot">
      <span>Usually takes 1–4 minutes</span>
      <a class="btn-line" href="/">{_BACK}Dashboard</a>
    </div>
  </section>
</main>
</body>
</html>"""


def _render_dashboard(
    client_name: str,
    today: str,
    destination: str,
    cms_status: str,
    month_label: str,
    stats: dict,
    error_banner: str,
    upload_box: str,
    example_keyword: str,
    plan_table: str,
    recent_drafts: str,
    recent_count: int,
    auto_box: str = "",
) -> str:
    total = stats["total"]
    meter = "".join(f'<i class="{"on" if i < stats["done"] else ""}"></i>' for i in range(total)) if total else "<i></i>"
    dest_note = (f"New articles upload to {destination} as {cms_status}."
                 if cms_status else "Articles are saved as local files only.")
    problems_cls = " alert-on" if stats["problems"] else ""
    return f"""<!doctype html>
<html lang="en">
<head>
{_COMMON_HEAD}
<title>{client_name} · AutoBlog</title>
</head>
<body>
<header class="band">
  <div class="container">
    {_bar(today, _dest_label(destination, cms_status))}
    <div class="hero">
      <div>
        <p class="kicker">SEO content · {month_label}</p>
        <h1>{client_name}</h1>
      </div>
      <p>Topics are planned, researched and written on schedule. {dest_note}</p>
    </div>
    <section class="stats" aria-label="This month">
      <div class="stat">
        <div class="stat-label">Completed</div>
        <div class="stat-value">{stats["done"]}<small>/ {total}</small></div>
        <div class="meter" style="--n: {max(total, 1)}" aria-hidden="true">{meter}</div>
      </div>
      <div class="stat">
        <div class="stat-label">In queue</div>
        <div class="stat-value">{stats["planned"]}</div>
        <div class="stat-note">Scheduled this month</div>
      </div>
      <div class="stat">
        <div class="stat-label">Needs attention</div>
        <div class="stat-value{problems_cls}">{stats["problems"]}</div>
        <div class="stat-note">Failed or skipped</div>
      </div>
      <div class="stat">
        <div class="stat-label">Destination</div>
        <div class="stat-value text">{destination}</div>
        <div class="stat-note">{f"Uploads as {cms_status}" if cms_status else "Saved locally"}</div>
      </div>
    </section>
  </div>
</header>

<main class="container">
  {error_banner}
  <div class="grid">
    <div>
      <section class="panel">
        <div class="panel-head"><h2>Write an article</h2></div>
        <div class="panel-body">
          <p class="lede">Generate one now, outside the schedule.</p>
          <form method="post" action="/generate"
                onsubmit="var b=document.getElementById('go');b.disabled=true;b.firstElementChild.textContent='Starting…';">
            <div class="field">
              <label for="k">Keyword or topic</label>
              <input id="k" class="input" name="keyword" required maxlength="200" autocomplete="off"
                     placeholder="e.g. {example_keyword}">
              <p class="hint">Topics already on the website are rejected before any AI quota is used.</p>
            </div>
            {upload_box}
            <button id="go" class="btn" type="submit"><span>Generate article</span>{_ARROW}</button>
          </form>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h2>Recent drafts</h2><span class="meta">{recent_count} files</span></div>
        {recent_drafts}
      </section>
    </div>

    <div>
      {auto_box}
      <section class="panel">
        <div class="panel-head"><h2>Content calendar</h2><span class="meta"><span class="m-hide">{month_label} · </span>{total} articles</span></div>
        {plan_table}
      </section>
    </div>
  </div>
</main>
</body>
</html>"""


def serve(client, port=8000, host="127.0.0.1", reload=False):
    if reload:
        import sys
        import time
        from pathlib import Path
        watch_dirs = [Path(__file__).parent, Path("clients")]
        def get_mtimes():
            mtimes = {}
            for d in watch_dirs:
                if d.exists():
                    for p in d.rglob("*.py"):
                        try: mtimes[p] = p.stat().st_mtime
                        except Exception: pass
                    for p in d.rglob("*.yaml"):
                        try: mtimes[p] = p.stat().st_mtime
                        except Exception: pass
            return mtimes

        initial_mtimes = get_mtimes()

        def watcher():
            while True:
                time.sleep(1)
                curr = get_mtimes()
                if curr != initial_mtimes:
                    print("\n[RELOAD] Detected file change, reloading web server...")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
        threading.Thread(target=watcher, daemon=True).start()

    drafts_dir = client.drafts_dir
    jobs: dict[str, dict] = {}
    lock = threading.Lock()

    def run_job(job_id, keyword, mode):
        try:
            upload = mode in ("draft", "published")
            path = pipeline.preview_article(client, keyword, upload=upload, status=mode if upload else None)["path"]
            update = {"status": "done", "draft": path.name}
        except Exception as e:
            print(f"[ERROR] {e}")
            update = {"status": "failed", "error": str(e)}
        with lock:
            jobs[job_id].update(update)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _get_stats(self, plan):
            items = (plan or {}).get("items") or []
            count = lambda *s: sum(1 for it in items if it.get("status", "planned") in s)  # noqa: E731
            return {"done": count("done"), "total": len(items), "planned": count("planned"),
                    "problems": count("failed", "skipped")}


        def _form(self, error=""):
            files = sorted(drafts_dir.glob("*.html"), reverse=True)[:8] if drafts_dir.exists() else []
            if files:
                recent_drafts = '<ul class="recent">' + "".join(
                    f'<li><a href="/drafts/{quote(f.name)}" title="{html.escape(f.name)}">'
                    f'<div class="recent-left">'
                    f'<span class="recent-name">{html.escape(name)}</span>'
                    f'<span class="recent-when">Saved: {when or "Draft"}</span>'
                    f'</div>'
                    f'<span class="recent-pill">Preview Article ↗</span>'
                    f'</a></li>'
                    for f in files
                    for name, when in [_draft_label(f.stem)]
                ) + '</ul>'
            else:
                recent_drafts = '<p class="empty">No drafts yet. Articles you generate will appear here.</p>'

            error_banner = (
                f'<div class="alert" role="alert"><b>Notice</b><span>{html.escape(error)}</span></div>'
            ) if error else ""

            cms_status = client.publish_status
            if cms_status:
                cms = html.escape(client.destination.title())
                opts = [("draft", "Draft", f"Review in {cms}"), ("published", "Publish", "Live on the site"),
                        ("local", "Local only", "Don't upload")]
                upload_box = (
                    '<fieldset class="choice"><legend>When it is ready</legend><div class="choice-opts">'
                    + "".join(f'<label><input type="radio" name="mode" value="{v}"{" checked" if v == cms_status else ""}>'
                              f'<span>{label}<small>{note}</small></span></label>' for v, label, note in opts)
                    + f'</div><p class="hint">Only for this article. Scheduled articles follow '
                      f'<b>Automatic publishing</b> ({cms_status}).</p></fieldset>'
                )
            else:
                upload_box = ""

            today = planner.local_today(client)
            plan = planner.load_plan(client, today.strftime("%Y-%m"))
            auto_box = self._auto_box(plan) if cms_status else ""
            example = (client.sources.keyword_seeds or ['GFRP rebar applications'])[0]

            body = _render_dashboard(
                client_name=html.escape(client.brand.name),
                today=today.strftime("%a, %d %b %Y"),
                destination=html.escape(client.destination.title()),
                cms_status=html.escape(cms_status),
                month_label=today.strftime("%B %Y"),
                stats=self._get_stats(plan),
                error_banner=error_banner,
                upload_box=upload_box,
                example_keyword=html.escape(example),
                plan_table=self._plan_html(plan, today.isoformat(), self._live_statuses(plan)),
                recent_drafts=recent_drafts,
                recent_count=len(files),
                auto_box=auto_box,
            )
            self._send(200, body)

        def _auto_box(self, plan):
            """Main setting: the status the scheduler uploads every planned article with."""
            st = client.publish_status
            cms = html.escape(client.destination.title())
            live = st == "published"
            nxt = next((it for it in (plan or {}).get("items", []) if it.get("status") == "planned"), None)
            next_line = (f'<p class="auto-next">Next: <b>{html.escape(nxt.get("date", ""))}</b> · '
                         f'{html.escape(nxt.get("title") or nxt.get("keyword") or "")}</p>') if nxt else ""
            if config.load_settings(client.id).get("publish_status"):
                default = client.publish_status_default
                source = (f'Set here on the dashboard. Choosing <b>{default}</b> again hands control back to '
                          f'<code>PUBLISH_STATUS</code> / config.yaml.')
            elif os.getenv("PUBLISH_STATUS", "").strip():
                source = 'Currently from <code>PUBLISH_STATUS</code> in .env. A choice here overrides it.'
            else:
                source = 'Currently from <code>config.yaml</code>. A choice here overrides it.'
            def btn(v, label, note):
                cls = ("on" if st == v else "") + (" live" if v == "published" else "")
                pressed = "true" if st == v else "false"
                return (f'<button type="submit" name="publish_status" value="{v}" class="{cls}" '
                        f'aria-pressed="{pressed}">{label}<small>{note}</small></button>')
            return (
                '<section class="panel auto">'
                '<div class="panel-head"><h2>Automatic publishing</h2><span class="meta">Used by the scheduler</span></div>'
                '<div class="auto-body"><div>'
                '<p class="auto-lede">When a planned date arrives, the article is written and uploaded to '
                f'{cms} as:</p>'
                f'<p class="auto-state"><em class="{"live" if live else ""}">'
                f'{"Published, live on the website" if live else "Draft, waiting for your review"}</em></p>'
                f'{next_line}</div>'
                '<form method="post" action="/settings" class="seg" '
                'onsubmit="return event.submitter.value!==\'published\'||event.submitter.classList.contains(\'on\')'
                '||confirm(\'Scheduled articles will go live on the website without review. Continue?\')">'
                + btn("draft", "Draft", f"Review in {cms} first")
                + btn("published", "Published", "Live automatically")
                + f'</form><p class="auto-note"><span>{source}</span>'
                  '<span>Takes effect from the next scheduled run.</span></p></div></section>'
            )

        def _live_statuses(self, plan):
            """documentId -> "draft"/"published" as Strapi has it now, so a post published in the admin
            does not get a Publish button. None when Strapi is not used or could not be read."""
            if client.destination != "strapi":
                return None
            if not any(pipeline.uploaded_draft(client, it.get("draft")) for it in (plan or {}).get("items", [])):
                return None
            blogs = strapi.list_blogs(client)
            return None if blogs is None else {b["documentId"]: b["status"] for b in blogs}

        def _cms_cell(self, it, live):
            """CMS column: Publish button for our drafts, a link once live, else the upload result."""
            up = pipeline.uploaded_draft(client, it.get("draft"))
            if not up:
                return html.escape(it.get("upload") or "—")
            doc = up["documentId"]
            status = up.get("status") if live is None else live.get(doc)
            admin = (strapi.admin_url(client, doc) if client.destination == "strapi"
                     else publisher.admin_url(client, doc))
            if status == "published":
                url = up.get("url") if up.get("status") == "published" else ""
                url = url or (f"{client.brand.website.rstrip('/')}{client.strapi.blog_path}/"
                              if client.destination == "strapi" else "")
                return (f'<span class="cms"><a class="cms-live" href="{html.escape(url)}" target="_blank" '
                        f'rel="noopener">Live</a></span>')
            if status != "draft":  # deleted in the CMS
                return '<span class="cms-draft">Not in CMS</span>'
            title = html.escape(it.get("title") or it.get("keyword") or "this article", quote=True)
            return (
                '<span class="cms">'
                f'<form method="post" action="/publish" data-title="{title}" '
                'onsubmit="return confirm(\'Publish \u201c\' + this.dataset.title + \'\u201d on the website now?\')">'
                f'<input type="hidden" name="draft" value="{html.escape(it["draft"], quote=True)}">'
                '<button class="btn-pub" type="submit">Publish</button></form>'
                f'<a class="cms-link" href="{html.escape(admin)}" target="_blank" rel="noopener">'
                f'Open in {html.escape(client.destination.title())}</a></span>'
            )

        def _plan_html(self, plan, today_iso, live=None):
            if not plan or not plan.get("items"):
                return '<p class="empty">No plan for this month yet. It is created automatically on the next scheduled run.</p>'

            rows = ""
            for it in plan["items"]:
                name = html.escape(it.get("title") or it.get("keyword") or "Untitled")
                if it.get("draft"):
                    name = f'<a href="/drafts/{quote(it["draft"])}">{name}</a>'

                status_val = it.get("status", "planned")
                status_cls = status_val if status_val in ("done", "planned", "failed", "skipped") else "planned"
                error = (f'<div class="c-error">{html.escape(it["last_error"])}</div>'
                         if it.get("last_error") and status_val in ("failed", "skipped") else "")
                day = it.get("date") or ""
                is_today = day == today_iso
                try:
                    parsed = datetime.strptime(day, "%Y-%m-%d")
                    pretty_day = parsed.strftime("%d %b")
                    weekday = "Today" if is_today else parsed.strftime("%A")
                except ValueError:
                    pretty_day, weekday = day or "—", ""

                row_cls = ' class="is-today"' if is_today else ""
                rows += (
                    f'<tr{row_cls}>'
                    f'<td class="c-date"><b>{html.escape(pretty_day)}</b><small>{weekday}</small></td>'
                    f'<td class="c-status"><span class="status status-{status_cls}">{html.escape(status_val.title())}</span></td>'
                    f'<td class="c-topic"><div class="c-title">{name}</div>{error}</td>'
                    f'<td class="c-cat"><span class="tag">{html.escape(it.get("category") or "General")}</span></td>'
                    f'<td class="c-cms">{self._cms_cell(it, live)}</td>'
                    f'</tr>'
                )

            return (
                '<div class="table-wrap"><table class="calendar"><thead><tr>'
                '<th style="width:150px">Date</th><th style="width:130px">Status</th>'
                '<th>Topic</th><th>Category</th><th class="c-cms">On website</th>'
                f'</tr></thead><tbody>{rows}</tbody></table></div>'
            )

        def do_GET(self):
            if self.path == "/":
                return self._form()
            if self.path.startswith("/drafts/"):
                name = unquote(self.path[len("/drafts/"):])
                f = drafts_dir / name
                # Only plain filenames inside the drafts folder — no path traversal.
                types = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
                         ".jpg": "image/jpeg"}
                if "/" not in name and "\\" not in name and f.suffix in types and f.is_file():
                    return self._send(200, f.read_bytes(), types[f.suffix])
            if self.path.startswith("/jobs/"):
                with lock:
                    job = dict(jobs.get(self.path[len("/jobs/"):], {}))
                if job.get("status") == "done":
                    return self._send(303, "", headers={"Location": f"/drafts/{quote(job['draft'])}"})
                if job.get("status") == "failed":
                    return self._form(f"Generation failed for \"{job['keyword']}\": {job['error']}")
                if job:
                    cms_status = job["mode"] if job["mode"] in ("draft", "published") else ""
                    return self._send(200, _render_job_page(
                        client_name=html.escape(client.brand.name),
                        today=planner.local_today(client).strftime("%a, %d %b %Y"),
                        keyword=html.escape(job["keyword"]),
                        started=job["started"],
                        destination=html.escape(client.destination.title()),
                        cms_status=html.escape(cms_status),
                        uploading=bool(cms_status),
                    ))
            self._send(404, "Not found", "text/plain; charset=utf-8")

        def do_POST(self):
            # Block forms posted from other websites open in the same browser (this page has no login).
            origin = self.headers.get("Origin")
            if origin and origin != "null" and urlparse(origin).netloc != self.headers.get("Host"):
                return self._send(403, "Forbidden", "text/plain; charset=utf-8")
            if self.path not in ("/generate", "/settings", "/publish"):
                return self._send(404, "Not found", "text/plain; charset=utf-8")
            length = min(int(self.headers.get("Content-Length") or 0), 10_000)
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            if self.path == "/publish":
                draft = form.get("draft", [""])[0]
                plan = planner.load_plan(client, planner.local_today(client).strftime("%Y-%m"))
                if not any(it.get("draft") == draft for it in (plan or {}).get("items", [])):
                    return self._form("That article is not in this month's calendar.")
                res = pipeline.publish_saved(client, draft)
                if res["result"] != "published":
                    return self._form(f"Could not publish: {res['reason']}")
                print(f"[WEB] Published from the dashboard: {draft}")
                return self._send(303, "", headers={"Location": "/"})
            if self.path == "/settings":
                status = form.get("publish_status", [""])[0]
                if not client.publish_status or status not in config.PUBLISH_STATUSES:
                    return self._form("Unknown setting.")
                config.save_publish_status(client, status)
                print(f"[WEB] Automatic publishing set to: {status}")
                return self._send(303, "", headers={"Location": "/"})
            keyword = form.get("keyword", [""])[0].strip()[:200]
            mode = form.get("mode", [""])[0]
            if mode not in ("draft", "published", "local"):
                mode = client.publish_status or "local"
            if not keyword:
                return self._form("Please enter a keyword.")
            hit = strapi.find_existing(strapi.list_blogs(client) or [], keyword=keyword)
            if hit:  # checked here too, so the page answers at once instead of starting a job
                return self._form(f'Not written: "{hit["title"]}" is already on the website ({hit["status"]}).')
            with lock:  # one article at a time: protects the daily free AI quota
                running = next((i for i, j in jobs.items() if j["status"] == "running"), None)
                if running is None:
                    running = uuid.uuid4().hex[:12]
                    jobs[running] = {"status": "running", "keyword": keyword, "mode": mode,
                                     "started": datetime.now().strftime("%H:%M:%S")}
                    threading.Thread(target=run_job, args=(running, keyword, mode), daemon=True).start()
            self._send(303, "", headers={"Location": f"/jobs/{running}"})

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[WEB] Listening on {host}:{port}. Open http://127.0.0.1:{port} in your browser (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[WEB] Stopped")
