import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../dialog";

function ControlledDialog({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger>Abrir diálogo</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Título</DialogTitle>
          <DialogDescription>Descripción del diálogo</DialogDescription>
        </DialogHeader>
        <p>Contenido del cuerpo</p>
        <DialogFooter>
          <button onClick={() => setOpen(false)}>Cancelar</button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

describe("Dialog", () => {
  it("does not render content when closed", () => {
    render(<ControlledDialog />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens via trigger and exposes role=dialog with aria-modal", async () => {
    render(<ControlledDialog />);
    await userEvent.click(screen.getByRole("button", { name: "Abrir diálogo" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("renders title, description and body when open", async () => {
    render(<ControlledDialog defaultOpen />);
    expect(screen.getByText("Título")).toBeInTheDocument();
    expect(screen.getByText("Descripción del diálogo")).toBeInTheDocument();
    expect(screen.getByText("Contenido del cuerpo")).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    render(<ControlledDialog defaultOpen />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes via the X button", async () => {
    render(<ControlledDialog defaultOpen />);
    await userEvent.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes via custom footer action", async () => {
    render(<ControlledDialog defaultOpen />);
    await userEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("calls onOpenChange when toggling", async () => {
    const onOpenChange = vi.fn();
    function Wrapper() {
      const [open, setOpen] = useState(false);
      return (
        <Dialog open={open} onOpenChange={(v) => { onOpenChange(v); setOpen(v); }}>
          <DialogTrigger>Abrir</DialogTrigger>
          <DialogContent>
            <DialogTitle>X</DialogTitle>
          </DialogContent>
        </Dialog>
      );
    }
    render(<Wrapper />);
    await userEvent.click(screen.getByRole("button", { name: "Abrir" }));
    expect(onOpenChange).toHaveBeenLastCalledWith(true);

    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });
});
