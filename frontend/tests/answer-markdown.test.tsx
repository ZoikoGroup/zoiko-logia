import { render } from "@testing-library/react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkMath from "remark-math";
import { describe, expect, it, vi } from "vitest";
import { ANSWER_MATH_OPTIONS, sanitizeAnswerMarkdown } from "@/lib/answer-markdown";

describe("answer Markdown math safety", () => {
  it("normalizes narrow no-break spaces before parsing", () => {
    const result = sanitizeAnswerMarkdown("Revenue: USD 2\u202F264\u202F000");
    expect(result).toBe("Revenue: USD 2 264 000");
    expect(result).not.toContain("\u202F");
  });

  it("renders currency and percentages as text without KaTeX warnings", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const { container } = render(
      <ReactMarkdown
        remarkPlugins={[[remarkMath, ANSWER_MATH_OPTIONS]]}
        rehypePlugins={[rehypeKatex]}
      >
        {sanitizeAnswerMarkdown("Revenue was $2\u202F264,000 and profit was $1\u202F155,000 at 51.02 %.")}
      </ReactMarkdown>,
    );

    expect(container.textContent).toContain("$2 264,000");
    expect(container.querySelector(".katex")).toBeNull();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("continues to render explicit display formulas", () => {
    const { container } = render(
      <ReactMarkdown
        remarkPlugins={[[remarkMath, ANSWER_MATH_OPTIONS]]}
        rehypePlugins={[rehypeKatex]}
      >
        {"$$\n\\text{Margin} = \\frac{\\text{Profit}}{\\text{Revenue}} \\times 100\n$$"}
      </ReactMarkdown>,
    );

    expect(container.querySelector(".katex-display")).not.toBeNull();
  });
});
