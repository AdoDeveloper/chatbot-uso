import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import { Switch } from "../switch";

describe("Switch", () => {
  it("renders with role=switch", () => {
    render(<Switch checked={false} />);
    expect(screen.getByRole("switch")).toBeInTheDocument();
  });

  it("reflects checked state via aria-checked", () => {
    const { rerender } = render(<Switch checked={false} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");

    rerender(<Switch checked={true} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("fires onCheckedChange with the toggled value", async () => {
    const onCheckedChange = vi.fn();
    render(<Switch checked={false} onCheckedChange={onCheckedChange} />);

    await userEvent.click(screen.getByRole("switch"));
    expect(onCheckedChange).toHaveBeenCalledTimes(1);
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it("toggles correctly across multiple clicks (controlled wrapper)", async () => {
    function Wrapper() {
      const [checked, setChecked] = useState(false);
      return <Switch checked={checked} onCheckedChange={setChecked} />;
    }
    render(<Wrapper />);
    const sw = screen.getByRole("switch");

    expect(sw).toHaveAttribute("aria-checked", "false");
    await userEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "true");
    await userEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "false");
  });

  it("does not fire onCheckedChange when disabled", async () => {
    const onCheckedChange = vi.fn();
    render(<Switch checked={false} onCheckedChange={onCheckedChange} disabled />);

    await userEvent.click(screen.getByRole("switch"));
    expect(onCheckedChange).not.toHaveBeenCalled();
  });

  it("forwards aria-label for screen readers", () => {
    render(<Switch checked={false} aria-label="Activar notificaciones" />);
    expect(screen.getByRole("switch", { name: "Activar notificaciones" })).toBeInTheDocument();
  });
});
