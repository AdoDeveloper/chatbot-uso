import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Alert, AlertTitle, AlertDescription } from "../alert";

describe("Alert", () => {
  it("renders title and description", () => {
    render(
      <Alert>
        <AlertTitle>Error</AlertTitle>
        <AlertDescription>Algo salió mal</AlertDescription>
      </Alert>,
    );
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getByText("Algo salió mal")).toBeInTheDocument();
  });

  it("applies destructive variant", () => {
    render(
      <Alert variant="destructive">
        <AlertDescription>Mensaje crítico</AlertDescription>
      </Alert>,
    );
    const alert = screen.getByText("Mensaje crítico").closest("[data-slot='alert']");
    expect(alert?.className).toMatch(/bg-destructive\/10/);
  });
});
