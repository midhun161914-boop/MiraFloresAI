#!/usr/bin/env node
// One-command runner (Node built-ins only, so it works before any `npm install`).
//
//   npm run dev     API (FastAPI, :8000, auto-reload) + UI (Vite, :5173, hot reload)
//   npm start       build the UI, then serve API + UI from FastAPI on :8000
//   npm test        backend tests + sanity check + frontend typecheck + WCAG contrast
//
// First run sets things up: creates backend/.venv and installs requirements if
// missing (or if requirements.txt changed), and installs frontend packages.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const backend = join(root, "backend");
const frontend = join(root, "frontend");
const win = process.platform === "win32";
const venvPy = join(backend, ".venv", win ? "Scripts/python.exe" : "bin/python");
const API_PORT = process.env.API_PORT ?? "8000";
const mode = process.argv[2] ?? "dev";

const color = { api: "\x1b[36m", ui: "\x1b[35m", setup: "\x1b[33m", reset: "\x1b[0m" };
const log = (tag, msg) => console.log(`${color[tag] ?? ""}[${tag}]${color.reset} ${msg}`);

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", shell: false, ...opts });
  if (r.status !== 0) {
    log("setup", `failed: ${cmd} ${args.join(" ")}`);
    process.exit(r.status ?? 1);
  }
}

function findSystemPython() {
  for (const cand of win ? ["python", "py"] : ["python3", "python"]) {
    const r = spawnSync(cand, ["-c", "import sys; print(sys.version_info >= (3, 11))"], { encoding: "utf8" });
    if (r.status === 0 && r.stdout.trim() === "True") return cand;
  }
  log("setup", "Python 3.11+ not found on PATH. Install it from python.org and re-run.");
  process.exit(1);
}

function ensureBackend() {
  if (!existsSync(venvPy)) {
    log("setup", "creating backend/.venv");
    run(findSystemPython(), ["-m", "venv", join(backend, ".venv")]);
  }
  const req = join(backend, "requirements.txt");
  const marker = join(backend, ".venv", ".requirements-installed");
  const stale = !existsSync(marker) || readFileSync(marker, "utf8") !== String(statSync(req).mtimeMs);
  if (stale) {
    log("setup", "installing backend requirements");
    run(venvPy, ["-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", req]);
    writeFileSync(marker, String(statSync(req).mtimeMs));
  }
}

function ensureFrontend() {
  if (!existsSync(join(frontend, "node_modules", "vite"))) {
    log("setup", "installing frontend packages");
    run(win ? "npm.cmd" : "npm", ["install", "--no-audit", "--no-fund"], { cwd: frontend, shell: win });
  }
}

const children = [];
function start(tag, cmd, args, cwd, env = {}) {
  const child = spawn(cmd, args, { cwd, env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] });
  const pipe = (stream) => {
    let buf = "";
    stream.on("data", (d) => {
      buf += d.toString();
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      lines.forEach((l) => l && log(tag, l));
    });
  };
  pipe(child.stdout);
  pipe(child.stderr);
  child.on("exit", (code) => {
    log(tag, `exited (${code})`);
    shutdown(code ?? 0);
  });
  children.push(child);
  return child;
}

let stopping = false;
function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const c of children) {
    if (c.exitCode !== null) continue;
    // uvicorn --reload spawns a worker; kill the whole tree.
    if (win) spawnSync("taskkill", ["/pid", String(c.pid), "/T", "/F"], { stdio: "ignore" });
    else c.kill("SIGTERM");
  }
  process.exit(code);
}
process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

const vite = join(frontend, "node_modules", "vite", "bin", "vite.js");
const tsc = join(frontend, "node_modules", "typescript", "bin", "tsc");
const uvicorn = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", API_PORT];

ensureBackend();
ensureFrontend();

if (mode === "dev") {
  start("api", venvPy, [...uvicorn, "--reload", "--reload-dir", "app"], backend, { PYTHONUNBUFFERED: "1" });
  start("ui", process.execPath, [vite, "--host", "127.0.0.1"], frontend, { API_PORT });
  log("setup", "Open http://localhost:5173  (API docs: http://localhost:8000/docs)  — Ctrl+C stops both");
} else if (mode === "start") {
  log("setup", "building frontend");
  run(process.execPath, [tsc, "-b"], { cwd: frontend });
  run(process.execPath, [vite, "build"], { cwd: frontend });
  start("api", venvPy, uvicorn, backend, { PYTHONUNBUFFERED: "1" });
  log("setup", `Open http://localhost:${API_PORT}  — Ctrl+C stops`);
} else if (mode === "test") {
  run(venvPy, ["-m", "pytest", "-q"], { cwd: backend });
  run(venvPy, ["scripts/sanity_check.py"], { cwd: backend, env: { ...process.env, PYTHONIOENCODING: "utf-8" } });
  run(process.execPath, [tsc, "-b"], { cwd: frontend });
  run(process.execPath, ["scripts/contrast.mjs"], { cwd: frontend });
  log("setup", "all checks passed");
} else {
  console.error(`unknown mode ${mode}; use dev | start | test`);
  process.exit(2);
}
