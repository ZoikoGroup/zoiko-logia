import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const roots = ["components/command-center"];
const banned = [
  "massarius", "home dashboard", "ask the ai", "chatbot", "new conversation",
  "chat history", "continue chatting", "ai uncertain", "data issue",
  "fully compliant", "guaranteed accurate", "your data is perfectly secure",
];

function files(path) {
  return readdirSync(path).flatMap((name) => {
    const target = join(path, name);
    return statSync(target).isDirectory() ? files(target) : [target];
  });
}

const violations = roots.flatMap(files).flatMap((file) => {
  const content = readFileSync(file, "utf8").toLowerCase();
  return banned.filter((phrase) => content.includes(phrase)).map((phrase) => `${file}: banned copy "${phrase}"`);
});

if (violations.length) {
  console.error(violations.join("\n"));
  process.exit(1);
}
console.log("Command Center copy check passed.");
