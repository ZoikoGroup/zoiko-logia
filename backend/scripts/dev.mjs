// `npm run dev` for the backend: start uvicorn with the project's own
// virtualenv when there is one, so it works whether or not the venv is
// activated (a conda `(base)` shell otherwise resolves `python` to an
// interpreter without the project's packages → ModuleNotFoundError).
import { createWriteStream, existsSync, mkdirSync, renameSync, statSync } from "node:fs";
import { execSync, spawn } from "node:child_process";
import { createServer } from "node:net";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const backend = join(dirname(fileURLToPath(import.meta.url)), "..");
const candidates = [
  join(backend, ".venv", "bin", "python"),          // macOS / Linux
  join(backend, ".venv", "Scripts", "python.exe"),  // Windows
];
const python = candidates.find((path) => existsSync(path)) ?? "python";
if (python === "python") {
  console.warn("backend/.venv not found — using `python` from PATH. Create it with: python -m venv .venv && .venv/bin/pip install -r requirements.txt");
}

// Output goes to the terminal as before AND to backend/logs/dev.log, so a
// failure ("Kriton could not complete this request") can be diagnosed from
// its traceback afterwards instead of only from a terminal that has scrolled
// or closed. The file is git-ignored.
//
// Appended, not truncated: truncating on start erased the record of a
// morning's failed question the moment the backend was restarted to fix it.
// Rolled to dev.log.1 past 20 MB so it cannot grow without bound.
const logs = join(backend, "logs");
mkdirSync(logs, { recursive: true });
const logPath = join(logs, "dev.log");
if (existsSync(logPath) && statSync(logPath).size > 20_000_000) renameSync(logPath, `${logPath}.1`);
const log = createWriteStream(logPath, { flags: "a" });
const stamp = () => new Date().toISOString();
const note = (line) => { const text = `[dev.mjs ${stamp()}] ${line}\n`; process.stdout.write(text); log.write(text); };

// Supervision: uvicorn's reloader restarts the server on code changes, but if
// the whole process dies (a crash, an out-of-memory kill) nothing brought it
// back and every question failed until someone restarted it by hand. Restart
// with backoff (1 s, 2 s, 4 s … 30 s); stop after 5 crashes within 5 minutes
// so a broken start-up does not loop forever. Ctrl+C stops for good.
const MAX_CRASHES = 5;
const CRASH_WINDOW_MS = 5 * 60_000;
let crashes = [];
let stopping = false;
let child = null;

function start() {
  note(`starting backend (uvicorn on port 8010)`);
  child = spawn(
    python,
    // --reload-dir app: editing tests or scripts must not restart the server
    // (and drop any question in flight) — only application code needs a reload.
    ["-m", "uvicorn", "app.main:app", "--reload", "--reload-dir", "app", "--port", "8010", ...process.argv.slice(2)],
    { cwd: backend, stdio: ["inherit", "pipe", "pipe"] },
  );
  child.stdout.on("data", (chunk) => { process.stdout.write(chunk); log.write(chunk); });
  child.stderr.on("data", (chunk) => { process.stderr.write(chunk); log.write(chunk); });
  child.on("exit", (code, signal) => {
    if (stopping) {
      note(`backend stopped (${signal ?? code})`);
      log.end(() => process.exit(0));
      return;
    }
    const now = Date.now();
    crashes = crashes.filter((at) => now - at < CRASH_WINDOW_MS).concat(now);
    note(`backend exited unexpectedly (code ${code}, signal ${signal}) — crash ${crashes.length} in 5 minutes`);
    if (crashes.length >= MAX_CRASHES) {
      note(`giving up after ${MAX_CRASHES} crashes in 5 minutes; fix the error above and run npm run dev again`);
      log.end(() => process.exit(code ?? 1));
      return;
    }
    const delay = Math.min(30_000, 1000 * 2 ** (crashes.length - 1));
    note(`restarting in ${delay / 1000} s`);
    setTimeout(start, delay);
  });
}

// A busy port is not a crash: retrying five times with backoff cannot free
// it (another backend — often an earlier `npm run dev` in another terminal —
// is still running). Check first, say who holds it, and stop.
const PORT = 8010;
function portFree(port) {
  return new Promise((resolve) => {
    const probe = createServer()
      .once("error", () => resolve(false))
      .once("listening", () => probe.close(() => resolve(true)))
      .listen(port, "127.0.0.1");
  });
}
function holder(port) {
  try {
    return execSync(`lsof -nP -iTCP:${port} -sTCP:LISTEN`, { encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    stopping = true;
    if (child && child.exitCode === null) child.kill(signal);
    else log.end(() => process.exit(0));
  });
}
if (await portFree(PORT)) {
  start();
} else {
  note(`port ${PORT} is already in use — another backend is probably running. Not starting.`);
  const who = holder(PORT);
  if (who) note(`held by:\n${who}`);
  note(`stop that process (Ctrl+C in its terminal, or kill <PID> from the list above), then run npm run dev again`);
  log.end(() => process.exit(1));
}
