// `npm run dev` for the backend: start uvicorn with the project's own
// virtualenv when there is one, so it works whether or not the venv is
// activated (a conda `(base)` shell otherwise resolves `python` to an
// interpreter without the project's packages → ModuleNotFoundError).
import { existsSync } from "node:fs";
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

const child = spawn(
  python,
  ["-m", "uvicorn", "app.main:app", "--reload", "--port", "8010", ...process.argv.slice(2)],
  { cwd: backend, stdio: "inherit" },
);
child.on("exit", (code) => process.exit(code ?? 0));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
