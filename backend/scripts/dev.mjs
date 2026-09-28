// `npm run dev` for the backend: start uvicorn with the project's own
// virtualenv when there is one, so it works whether or not the venv is
// activated (a conda `(base)` shell otherwise resolves `python` to an
// interpreter without the project's packages → ModuleNotFoundError).
import { createWriteStream, existsSync, mkdirSync } from "node:fs";
import { spawn } from "node:child_process";
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
// or closed. The file is git-ignored and truncated on each start.
mkdirSync(join(backend, "logs"), { recursive: true });
const log = createWriteStream(join(backend, "logs", "dev.log"), { flags: "w" });
const child = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--reload", "--port", "8010", ...process.argv.slice(2)],
  { cwd: backend, stdio: ["inherit", "pipe", "pipe"] },
);
child.stdout.on("data", (chunk) => { process.stdout.write(chunk); log.write(chunk); });
child.stderr.on("data", (chunk) => { process.stderr.write(chunk); log.write(chunk); });
child.on("exit", (code) => process.exit(code ?? 0));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
