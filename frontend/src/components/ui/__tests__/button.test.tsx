import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Button } from "../button";

describe("Button", () => {
  it("renders its label", () => {
    render(<Button>Guardar</Button>);
    expect(screen.getByRole("button", { name: "Guardar" })).toBeInTheDocument();
  });

  it("fires onClick when clicked", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Confirmar</Button>);
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("does not fire onClick when disabled", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick} disabled>Bloqueado</Button>);
    await userEvent.click(screen.getByRole("button", { name: "Bloqueado" }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("propagates an aria-label to the rendered element", () => {
    render(
      <Button aria-label="Cerrar diálogo">
        <span aria-hidden="true">×</span>
      </Button>,
    );
    expect(screen.getByRole("button", { name: "Cerrar diálogo" })).toBeInTheDocument();
  });

  it("applies the destructive variant class", () => {
    render(<Button variant="destructive">Borrar</Button>);
    const btn = screen.getByRole("button", { name: "Borrar" });
    // Test the public-facing data attribute that styling hooks off.
    expect(btn).toHaveAttribute("data-slot", "button");
    // The cva-generated class for destructive includes "destructive" somewhere.
    expect(btn.className).toMatch(/destructive/);
  });
});
