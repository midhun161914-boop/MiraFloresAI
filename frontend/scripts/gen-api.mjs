// Regenerate src/api/schema.d.ts from the FastAPI OpenAPI schema so the
// TypeScript client always matches the Pydantic models.
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const backend = resolve(here, "../../backend");
const py = process.platform === "win32"
  ? join(backend, ".venv", "Scripts", "python.exe")
  : join(backend, ".venv", "bin", "python");
const out = resolve(here, "../src/api/openapi.json");

execFileSync(existsSync(py) ? py : "python", [join(backend, "scripts", "export_openapi.py"), out], {
  stdio: "inherit",
  cwd: backend,
});
execFileSync(process.execPath, [
  resolve(here, "../node_modules/openapi-typescript/bin/cli.js"), out, "-o", resolve(here, "../src/api/schema.d.ts"),
], { stdio: "inherit" });
