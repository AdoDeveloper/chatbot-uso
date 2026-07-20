/**
 * CSS injected into the Shadow DOM — fully isolated from the host page.
 * Variables at top for easy theming:
 *   --color-primary  main brand blue
 *   --color-bubble   bubble button background
 */

export const STYLES = `
:host {
  --color-primary: #1e3a8a;
  --color-primary-hover: #1d4ed8;
  --color-bubble: #1e3a8a;
  z-index: 2147483647;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  font-size: 15px;
  line-height: 1.5;
  color: #1a1a1a;
  box-sizing: border-box;
}

*, *::before, *::after {
  box-sizing: border-box;
}

/* ── Root wrapper ─────────────────────────────────────────────────────── */

.root {
  position: fixed;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
}

.root[data-position="bottom-right"] { bottom: 1.5rem; right: 1.5rem; flex-direction: column-reverse; align-items: flex-end; }
.root[data-position="bottom-left"]  { bottom: 1.5rem; left: 1.5rem;  flex-direction: column-reverse; align-items: flex-start; }
.root[data-position="top-right"]    { top: 1.5rem;    right: 1.5rem; flex-direction: column;         align-items: flex-end; }
.root[data-position="top-left"]     { top: 1.5rem;    left: 1.5rem;  flex-direction: column;         align-items: flex-start; }

/* ── Bubble ──────────────────────────────────────────────────────────── */

.bubble {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: var(--color-bubble);
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(30, 58, 138, 0.4);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.bubble:hover {
  transform: scale(1.08);
  box-shadow: 0 6px 22px rgba(30, 58, 138, 0.5);
}

.bubble:active {
  transform: scale(0.94);
}

/* ── Panel ────────────────────────────────────────────────────────────── */

.panel {
  position: absolute;
  bottom: calc(100% + 12px);
  right: 0;
  width: 380px;
  height: 520px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.16), 0 2px 8px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transform-origin: bottom right;
  transform: scale(0.94) translateY(12px);
  opacity: 0;
  pointer-events: none;
  transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.18s ease;
}

.panel-open {
  transform: scale(1) translateY(0);
  opacity: 1;
  pointer-events: all;
}

/* ── Header ──────────────────────────────────────────────────────────── */

.header {
  background: linear-gradient(135deg, var(--color-primary) 0%, #2563eb 100%);
  color: #fff;
  padding: 14px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.header-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(255,255,255,0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}

.header-info {
  flex: 1;
}

.header-name {
  font-weight: 600;
  font-size: 14px;
  display: block;
}

.header-status {
  font-size: 11px;
  color: rgba(255,255,255,0.75);
}

.close-btn,
.header-btn {
  background: none;
  border: none;
  color: rgba(255,255,255,0.75);
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
  padding: 4px 7px;
  border-radius: 6px;
  transition: color 0.15s, background 0.15s;
  display: flex;
  align-items: center;
}

.close-btn:hover,
.header-btn:hover {
  color: #fff;
  background: rgba(255,255,255,0.15);
}

/* El botón de vaciar es secundario al de cerrar — un toque más sutil. */
.header-btn {
  margin-right: 2px;
  opacity: 0.85;
}

/* ── Messages area ───────────────────────────────────────────────────── */

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  scroll-behavior: smooth;
}

.messages::-webkit-scrollbar { width: 4px; }
.messages::-webkit-scrollbar-track { background: transparent; }
.messages::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 4px; }

/* ── Message rows ────────────────────────────────────────────────────── */

.msg-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  max-width: 92%;
  animation: msg-in 0.18s ease;
}

.msg-row-user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.msg-row-assistant {
  align-self: flex-start;
}

@keyframes msg-in {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

.msg-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.08);
}

.msg {
  display: flex;
  flex-direction: column;
  min-width: 0;  /* permite que el contenido truncate sin desbordar el row */
}

.msg-user  { align-self: flex-end; }
.msg-assistant { align-self: flex-start; }

/* User bubble */
.user-text {
  background: var(--color-primary);
  color: #fff;
  padding: 9px 14px;
  border-radius: 18px 18px 4px 18px;
  font-size: 14px;
  line-height: 1.55;
  word-break: break-word;
  white-space: pre-wrap;
}

/* ── Markdown output (assistant) ─────────────────────────────────────── */

.md {
  background: #f3f4f6;
  padding: 10px 14px;
  border-radius: 18px 18px 18px 4px;
  font-size: 14px;
  line-height: 1.65;
  word-break: break-word;
  overflow-x: auto;
}

.md p { margin: 0 0 7px; }
.md p:last-child { margin-bottom: 0; }
.md h1 { font-size: 17px; font-weight: 700; margin: 10px 0 5px; }
.md h2 { font-size: 15px; font-weight: 700; margin: 10px 0 5px; }
.md h3 { font-size: 14px; font-weight: 600; margin: 8px 0 4px; }
.md ul, .md ol { margin: 5px 0 5px 18px; padding: 0; }
.md li { margin: 3px 0; }
.md strong { font-weight: 700; }
.md em { font-style: italic; }
.md a { color: #2563eb; text-decoration: underline; word-break: break-all; }
.md img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 8px 0;
  border-radius: 10px;
  border: 1px solid color-mix(in srgb, var(--color-primary) 20%, transparent);
}
.md p:has(> img) { display: flex; flex-direction: column; gap: 8px; margin: 8px 0; }
.md p:has(> img) img { margin: 0; }
.md a:has(> img) { padding: 0; border: 0; background: transparent; text-decoration: none; }
.md a.pdf-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 4px 0;
  padding: 7px 12px;
  background: color-mix(in srgb, var(--color-primary) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-primary) 30%, transparent);
  border-radius: 8px;
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 600;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
  font-size: 0;
}
.md a.pdf-link::before {
  content: "";
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  background-color: currentColor;
  -webkit-mask: no-repeat center / contain url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/%3E%3Cpolyline points='14 2 14 8 20 8'/%3E%3C/svg%3E");
  mask: no-repeat center / contain url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/%3E%3Cpolyline points='14 2 14 8 20 8'/%3E%3C/svg%3E");
}
.md a.pdf-link::after {
  content: "PDF";
  flex: 0 0 auto;
  font-size: 13px;
}
.md a.pdf-link:hover { background: color-mix(in srgb, var(--color-primary) 18%, transparent); }

.md code {
  background: rgba(0,0,0,0.06);
  padding: 1px 5px;
  border-radius: 4px;
  font-family: "Fira Code", "Cascadia Code", Consolas, monospace;
  font-size: 12.5px;
}

.md pre {
  background: #1e293b;
  color: #e2e8f0;
  padding: 12px 14px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.md pre code {
  background: transparent;
  color: inherit;
  padding: 0;
  font-size: 12.5px;
  border-radius: 0;
}

.md blockquote {
  border-left: 3px solid #93c5fd;
  margin: 6px 0;
  padding: 3px 12px;
  color: #6b7280;
  background: rgba(147,197,253,0.1);
  border-radius: 0 6px 6px 0;
}

.md table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin: 6px 0;
}

.md th {
  background: #e5e7eb;
  padding: 6px 8px;
  text-align: left;
  font-weight: 600;
  border: 1px solid #d1d5db;
}

.md td {
  padding: 5px 8px;
  border: 1px solid #e5e7eb;
}

.md hr {
  border: none;
  border-top: 1px solid #e5e7eb;
  margin: 8px 0;
}

/* Streaming cursor */
.cursor {
  display: inline-block;
  animation: blink 0.9s step-end infinite;
  color: var(--color-primary);
  font-weight: 700;
}
@keyframes blink { 50% { opacity: 0; } }

/* Typing indicator (3 dots — visible while waiting for first token) */
.typing-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 0;
  height: 20px;
}
.typing-dots span {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-primary);
  opacity: 0.5;
  animation: typing-bounce 1.2s ease-in-out infinite;
}
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing-bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
  40%           { transform: translateY(-5px); opacity: 1; }
}

/* ── Sources ─────────────────────────────────────────────────────────── */

.sources { margin-top: 6px; }

.sources-toggle {
  background: none;
  border: 1px solid #d1d5db;
  color: #6b7280;
  font-size: 11.5px;
  padding: 3px 10px;
  border-radius: 12px;
  cursor: pointer;
  font-family: inherit;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}

.sources-toggle:hover {
  border-color: #9ca3af;
  color: #374151;
  background: #f9fafb;
}

.sources-list {
  margin: 7px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.source-item {
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px 10px;
}

.source-header {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.source-name {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
  word-break: break-all;
}

.source-score {
  font-size: 11px;
  color: #9ca3af;
  background: #f3f4f6;
  padding: 1px 6px;
  border-radius: 8px;
}

.source-text {
  margin: 4px 0 0;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ── Input row ───────────────────────────────────────────────────────── */

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  padding: 10px 12px 12px;
  border-top: 1px solid #f0f0f0;
  background: #fff;
  flex-shrink: 0;
}

.input {
  flex: 1;
  border: 1.5px solid #e5e7eb;
  border-radius: 22px;
  padding: 10px 16px;
  font-size: 14px;
  font-family: inherit;
  line-height: 1.5;
  resize: none;
  outline: none;
  max-height: 120px;
  overflow-y: auto;
  background: #fff;
  transition: border-color 0.15s, box-shadow 0.15s;
  color: #1a1a1a;
}

.input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-primary) 15%, transparent);
}

.input::placeholder { color: #9ca3af; }

.input:disabled {
  background: #f3f4f6;
  color: #9ca3af;
  cursor: not-allowed;
}

/* ── Send button ─────────────────────────────────────────────────────── */

.send-btn {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.15s, transform 0.1s;
}

.send-btn:hover:not(:disabled) { background: var(--color-primary-hover); }
.send-btn:active:not(:disabled) { transform: scale(0.9); }
.send-btn:disabled { background: #93c5fd; cursor: not-allowed; }

/* ── Spinner ─────────────────────────────────────────────────────────── */

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.65s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* ── Message action buttons ────────────────────────────────────────── */

.msg-actions {
  display: flex;
  gap: 2px;
  margin-top: 6px;
  opacity: 0;
  transition: opacity 0.15s ease;
}

.msg-assistant:hover .msg-actions {
  opacity: 1;
}

.action-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #9ca3af;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.15s, background 0.15s;
  padding: 0;
}

.action-btn:hover {
  background: #f3f4f6;
  color: #374151;
}

.action-active {
  color: var(--color-primary) !important;
}

.action-positive {
  color: #15803d !important;
}

.action-negative {
  color: #ef4444 !important;
}

/* ── Quick replies (conversation starters) ──────────── */

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px 4px;
  border-top: 1px solid rgba(0,0,0,0.04);
}

.suggestion-btn {
  background: #fff;
  color: var(--color-primary);
  border: 1px solid var(--color-primary);
  border-radius: 16px;
  padding: 6px 12px;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, transform 0.1s;
  font-family: inherit;
  text-align: left;
  line-height: 1.3;
}

.suggestion-btn:hover {
  background: var(--color-primary);
  color: #fff;
}

.suggestion-btn:active {
  transform: scale(0.97);
}

/* ── Bubble wrapper (necesario para posicionar el badge) ────────────── */

.bubble-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

/* ── Badge de no leídos ──────────────────────────────────────────────── */

.badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 18px;
  height: 18px;
  padding: 0 4px;
  background: #ef4444;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
  pointer-events: none;
  animation: badge-pop 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  border: 2px solid transparent;
}

@keyframes badge-pop {
  from { transform: scale(0.5); opacity: 0; }
  to   { transform: scale(1);   opacity: 1; }
}

/* ── Launcher label (etiqueta junto al launcher) ─────────────────────── */

.launcher-label-wrap {
  display: flex;
  align-items: center;
  cursor: pointer;
  animation: proactive-in 0.35s ease 0.6s both;
}

.launcher-label-text {
  background: #fff;
  color: #111827;
  padding: 7px 13px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
  box-shadow: 0 2px 10px rgba(0,0,0,0.12);
  white-space: nowrap;
  transition: background 0.15s;
}

.launcher-label-wrap:hover .launcher-label-text {
  background: #f3f4f6;
}

/* ── Kebab menu (⋮) ──────────────────────────────────────────────────── */

.kebab-wrapper {
  position: relative;
}

.kebab-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  min-width: 180px;
  overflow: hidden;
  z-index: 10;
  animation: kebab-in 0.14s ease;
}

@keyframes kebab-in {
  from { opacity: 0; transform: translateY(-6px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0)   scale(1); }
}

.kebab-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 10px 14px;
  background: none;
  border: none;
  font-size: 13px;
  font-family: inherit;
  color: #374151;
  cursor: pointer;
  text-align: left;
  transition: background 0.12s;
}

.kebab-item:hover {
  background: #f3f4f6;
}

.kebab-item + .kebab-item {
  border-top: 1px solid #f3f4f6;
}

.kebab-item-end {
  color: #ef4444;
}

.kebab-item-end:hover {
  background: #fef2f2;
}

/* ── Modo offline ────────────────────────────────────────────────────── */

.offline-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px 20px;
  text-align: center;
}

.offline-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #374151;
}

.offline-desc {
  margin: 0;
  font-size: 13px;
  color: #9ca3af;
  line-height: 1.5;
  max-width: 240px;
}

/* ── Proactive bubble (mensaje sobre el launcher cerrado) ──────────── */

.proactive-bubble {
  position: absolute;
  bottom: 8px;
  right: 72px;
  max-width: 240px;
  background: #fff;
  color: #111827;
  padding: 10px 14px;
  border-radius: 16px 16px 4px 16px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  font-size: 13px;
  line-height: 1.45;
  cursor: pointer;
  animation: proactive-in 0.4s ease 1.2s both;
}

.proactive-bubble:hover {
  background: #f9fafb;
}

.proactive-text {
  display: block;
}

@keyframes proactive-in {
  from { opacity: 0; transform: translateY(6px) scale(0.96); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* ── CSAT survey ─────────────────────────────────────────────────────── */

.csat-panel {
  border-top: 1px solid #f0f0f0;
  padding: 10px 14px 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  background: #fafafa;
  flex-shrink: 0;
}

.csat-question {
  margin: 0;
  font-size: 13px;
  color: #374151;
  font-weight: 500;
  text-align: center;
}

.csat-stars {
  display: flex;
  gap: 4px;
}

.csat-star {
  background: none;
  border: none;
  font-size: 26px;
  color: #d1d5db;
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
  transition: color 0.12s, transform 0.1s;
}

.csat-star:hover,
.csat-star:focus-visible {
  color: #f59e0b;
  transform: scale(1.15);
}

.csat-optional {
  font-weight: 400;
  color: #6b7280;
  font-size: 11.5px;
}

.csat-stars-preview {
  pointer-events: none;
}

.csat-star-preview {
  font-size: 22px;
  color: #d1d5db;
  padding: 0 2px;
  line-height: 1;
}

.csat-star-filled {
  color: #f59e0b;
}

.csat-comment {
  width: 100%;
  border: 1.5px solid #d1d5db;
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
  line-height: 1.5;
  resize: none;
  outline: none;
  color: #111827;
  background: #fff;
  transition: border-color 0.15s;
}

.csat-comment:focus {
  border-color: #2563eb;
}

.csat-comment::placeholder {
  color: #9ca3af;
}

.csat-char-count {
  margin: 0;
  font-size: 11px;
  color: #6b7280;
  text-align: right;
  width: 100%;
}

.csat-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: 8px;
}

.csat-skip {
  background: none;
  border: none;
  color: #6b7280;
  font-size: 11.5px;
  cursor: pointer;
  padding: 2px 6px;
  font-family: inherit;
  text-decoration: underline;
  transition: color 0.12s;
}

.csat-skip:hover { color: #374151; }

.csat-submit-btn {
  background: #1e3a8a;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 12.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s;
}

.csat-submit-btn:hover {
  background: #1d4ed8;
}

.csat-thanks-wrap {
  border-top: 1px solid #f0f0f0;
  background: #f0fdf4;
  flex-shrink: 0;
}

.csat-thanks {
  padding: 8px 14px;
  font-size: 13px;
  color: #166534;
  font-weight: 500;
  text-align: center;
}

.csat-thanks-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 14px 10px;
  flex-wrap: wrap;
}

.csat-thanks-btn {
  background: #fff;
  border: 1px solid #bbf7d0;
  color: #166534;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.csat-thanks-btn:hover {
  background: #dcfce7;
  border-color: #86efac;
}

/* ── Escalamiento — solicitud de contacto ────────────────────────────── */

.escal-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 12px 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}

/* Estado de confirmación: la tarjeta se tiñe de verde suave. */
.escal-card-done {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.escal-footer {
  display: flex;
  justify-content: center;
  padding: 4px 14px 6px;
  flex-shrink: 0;
}

.escal-footer-btn {
  background: none;
  border: none;
  color: var(--color-primary);
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  padding: 2px 4px;
  text-decoration: underline;
  text-underline-offset: 3px;
  opacity: 0.8;
  transition: opacity 0.15s;
}

.escal-footer-btn:hover {
  opacity: 1;
}

.escal-question {
  margin: 0;
  font-size: 13px;
  color: #374151;
  font-weight: 500;
  line-height: 1.45;
}

.escal-btn-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.escal-yes-btn {
  background: var(--color-primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 12.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s;
  flex: 1;
}

.escal-yes-btn:hover {
  background: var(--color-primary-hover);
}

.escal-no-btn {
  background: transparent;
  color: #6b7280;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.escal-no-btn:hover {
  background: #f3f4f6;
  color: #374151;
}

.escal-type-row {
  display: flex;
  gap: 14px;
}

.escal-radio-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: #374151;
  cursor: pointer;
}

.escal-input {
  width: 100%;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  font-family: inherit;
  color: #111;
  outline: none;
  transition: border-color 0.15s;
  background: #fff;
}

.escal-input::placeholder {
  color: #9ca3af;
  opacity: 0.7;
}

.escal-input:focus {
  border-color: var(--color-primary);
}

.escal-form-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.escal-cancel-btn {
  background: transparent;
  color: #6b7280;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
}

.escal-cancel-btn:hover {
  background: #f3f4f6;
}

.escal-submit-btn {
  background: var(--color-primary);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 6px 16px;
  font-size: 12.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s;
}

.escal-submit-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.escal-submit-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.escal-done {
  margin: 0;
  font-size: 13px;
  color: #065f46;
  font-weight: 600;
  line-height: 1.5;
  display: flex;
  align-items: center;
  gap: 8px;
}

.escal-input-label {
  display: block;
  font-size: 11.5px;
  font-weight: 600;
  color: #4b5563;
  margin-bottom: 3px;
}

.escal-error {
  margin: 4px 0 0;
  font-size: 11.5px;
  color: #b91c1c;
  font-weight: 500;
}

/* Input inválido: borde rojo para reforzar el mensaje de error. */
.escal-input[aria-invalid="true"] {
  border-color: #b91c1c;
}

.escal-input[aria-invalid="true"]:focus {
  border-color: #b91c1c;
  box-shadow: 0 0 0 2px rgba(185, 28, 28, 0.15);
}

/* Foco visible en radios y botones para navegación por teclado. */
.escal-radio-label input:focus-visible,
.escal-submit-btn:focus-visible,
.escal-cancel-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

/* ── Responsive (small screens) ─────────────────────────────────────── */

  @media (max-width: 440px) {
  .root[data-position="bottom-right"] { bottom: 1rem; right: 1rem; }
  .root[data-position="bottom-left"]  { bottom: 1rem; left: 1rem; }
  .root[data-position="top-right"]    { top: 1rem; right: 1rem; }
  .root[data-position="top-left"]     { top: 1rem; left: 1rem; }

  /* Panel a pantalla completa en móvil (WhatsApp/Intercom style). */
  .panel {
    position: fixed;
    inset: 0;
    width: 100vw;
    width: 100dvw;
    height: 100vh;
    height: 100dvh;
    border-radius: 0;
    transform-origin: center;
    transform: scale(1) translateY(0);
  }
  .panel-open {
    transform: scale(1) translateY(0);
  }
  .proactive-bubble { display: none; }
}

/* Pantallas de poca altura con ancho &gt; 440px: limita el alto del panel. */
@media (max-height: 600px) and (min-width: 441px) {
  .panel {
    height: min(520px, calc(100vh - 90px));
    height: min(520px, calc(100dvh - 90px));
  }
}

/* ── Accesibilidad ──────────────────────────────────────────────────── */

/* Escala de texto: afecta el contenido de los mensajes y las burbujas. */
.panel[data-text-scale="sm"] .msg { font-size: 12.5px; }
.panel[data-text-scale="md"] .msg { font-size: 14px; }
.panel[data-text-scale="lg"] .msg { font-size: 16.5px; line-height: 1.55; }
.panel[data-text-scale="lg"] .user-text { font-size: 16.5px; }

/* Alto contraste: texto más oscuro, bordes más marcados, burbujas más nítidas. */
.panel[data-contrast="high"] .md {
  background: #e5e7eb;
  color: #000;
  border: 1px solid #6b7280;
}
.panel[data-contrast="high"] .messages { color: #000; }
.panel[data-contrast="high"] .input {
  border: 2px solid #374151;
  color: #000;
}
.panel[data-contrast="high"] .header-status { color: #fff; }

.a11y-panel {
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
  padding: 12px 14px;
  flex-shrink: 0;
}

.a11y-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.a11y-panel-title {
  font-size: 13px;
  font-weight: 700;
  color: #111827;
}

.a11y-close {
  background: none;
  border: none;
  color: #6b7280;
  cursor: pointer;
  padding: 2px;
  display: flex;
  border-radius: 4px;
}
.a11y-close:hover { background: #e5e7eb; color: #111827; }

.a11y-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
}

.a11y-label {
  font-size: 12.5px;
  color: #374151;
  font-weight: 500;
}

.a11y-scale {
  display: flex;
  gap: 4px;
}

.a11y-scale-btn {
  width: 30px;
  height: 30px;
  border: 1px solid #d1d5db;
  background: #fff;
  border-radius: 8px;
  color: #374151;
  cursor: pointer;
  font-weight: 700;
  font-family: inherit;
  line-height: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.a11y-scale-btn:hover { background: #f3f4f6; }
.a11y-scale-active {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
}
.a11y-scale-btn:focus-visible,
.a11y-toggle:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.a11y-toggle {
  width: 42px;
  height: 24px;
  border-radius: 999px;
  border: none;
  background: #d1d5db;
  position: relative;
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}
.a11y-toggle-on { background: var(--color-primary); }
.a11y-toggle-knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.15s;
}
.a11y-toggle-on .a11y-toggle-knob { transform: translateX(18px); }

.a11y-hint {
  margin: 8px 0 0;
  font-size: 11px;
  color: #6b7280;
  line-height: 1.4;
}
`;
