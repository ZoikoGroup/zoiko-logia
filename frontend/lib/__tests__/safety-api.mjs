import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../safety-api.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function loadApi(fetch) {
  const exports = {};
  runInNewContext(compiled, {
    exports,
    process: { env: {} },
    require(name) {
      assert.equal(name, "@/lib/session-token");
      return { getCurrentAccessToken: () => "verified-session" };
    },
    fetch,
  });
  return exports;
}

const authenticated = loadApi(async (_url, options) => {
  assert.equal(options.headers.Authorization, "Bearer verified-session");
  return { ok: true, json: async () => [] };
});
await authenticated.getEscalations();

const denied = loadApi(async () => ({
  ok: false,
  json: async () => ({ detail: "Missing required permission: safety.manage" }),
}));
await assert.rejects(denied.actOnEscalation("case", "approve", "spoof"), /safety.manage/);
await assert.rejects(denied.createSafetyOverride({}), /safety.manage/);

const unavailable = loadApi(async () => { throw new Error("Network unavailable"); });
const result = await unavailable.validateOutput("Unverified advice");
assert.equal(result.is_safe, false);
assert.equal(result.cleaned_text, "");
assert.equal(result.violations.length, 1);
await assert.rejects(unavailable.createSafetyOverride({}), /Network unavailable/);
console.log("Safety API authentication, action failures, and validation fallback passed.");
