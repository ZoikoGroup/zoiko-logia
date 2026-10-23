import { describe, expect, it } from "vitest";
import { chatIdFromUrl, chatUrl, type Conversation } from "@/lib/ask-kriton-storage";

const chats = [{ id: "c1" }, { id: "c2" }] as Conversation[];

describe("which chat Ask Kriton opens", () => {
  it("starts a new chat when arriving at plain /ask-kriton (dashboard, sidebar, page links)", () => {
    expect(chatIdFromUrl("", chats)).toBeNull();
  });

  it("keeps the chat named in the URL across a reload", () => {
    expect(chatIdFromUrl("?chat=c2", chats)).toBe("c2");
  });

  it("ignores a chat id that no longer exists", () => {
    expect(chatIdFromUrl("?chat=deleted", chats)).toBeNull();
  });

  it("writes the open chat into the address, and removes it for a new chat", () => {
    expect(chatUrl("http://localhost:3000/ask-kriton", "c1")).toBe("/ask-kriton?chat=c1");
    expect(chatUrl("http://localhost:3000/ask-kriton?chat=c1&x=1", null)).toBe("/ask-kriton?x=1");
  });
});
