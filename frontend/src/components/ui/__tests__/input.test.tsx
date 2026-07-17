import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Input } from "../input";

describe("Input", () => {
  it("renders with placeholder", () => {
    render(<Input placeholder="Correo electrónico" />);
    expect(screen.getByPlaceholderText("Correo electrónico")).toBeInTheDocument();
  });

  it("accepts typed text", async () => {
    render(<Input aria-label="name" />);
    const input = screen.getByRole("textbox", { name: "name" });
    await userEvent.type(input, "test@example.com");
    expect(input).toHaveValue("test@example.com");
  });

  it("forwards ref to the DOM element", () => {
    let ref: HTMLInputElement | null = null;
    render(
      <Input
        ref={(el) => { ref = el; }}
        aria-label="ref-test"
      />,
    );
    expect(ref).toBeInstanceOf(HTMLInputElement);
  });
});
