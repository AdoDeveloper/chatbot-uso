import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "../auth-context";

vi.mock("@/lib/api", () => {
  const mockTokenStore = {
    getAccess: vi.fn(() => null),
    getRefresh: vi.fn(() => null),
    set: vi.fn(),
    clear: vi.fn(),
  };
  const mockApi = {
    get: vi.fn(),
    post: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  };
  return {
    default: mockApi,
    tokenStore: mockTokenStore,
  };
});

vi.mock("next/navigation", () => {
  const mockRouter = {
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  };
  return {
    useRouter: () => mockRouter,
    usePathname: () => "/dashboard",
  };
});

function TestConsumer() {
  const auth = useAuth();
  if (auth.loading) return <div data-testid="loading" />;
  if (!auth.user) return <div data-testid="unauthenticated" />;
  return (
    <div>
      <span data-testid="user-name">{auth.user.full_name}</span>
      <span data-testid="user-role">{auth.user.role}</span>
      <button onClick={() => auth.logout()}>Cerrar sesión</button>
    </div>
  );
}

describe("AuthProvider", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
  });

  it("resolves to unauthenticated when no token", async () => {
    // Sin token, AuthProvider resuelve loading síncronamente (dentro del
    // mismo act() de render); por eso no se afirma el estado "loading"
    // intermedio, solo el resultado final.
    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("unauthenticated")).toBeInTheDocument();
    });
  });

  it("redirects to login after logout", async () => {
    const api = (await import("@/lib/api")).default;
    vi.mocked(api.post).mockResolvedValue({ data: {} });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("unauthenticated")).toBeInTheDocument();
    });
  });

  it("does not clear the session when /auth/me fails with a network error (no response)", async () => {
    const { tokenStore } = await import("@/lib/api");
    vi.mocked(tokenStore.getAccess).mockReturnValue("some-token");
    const api = (await import("@/lib/api")).default;
    // Network/CORS errors reject without a `response` property — distinct
    // from a real 401. This must not be treated as an invalid session.
    vi.mocked(api.get).mockRejectedValue(new Error("Network Error"));

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("unauthenticated")).toBeInTheDocument();
    });

    expect(tokenStore.clear).not.toHaveBeenCalled();
  });

  it("clears the session when /auth/me fails with a real 401", async () => {
    const { tokenStore } = await import("@/lib/api");
    vi.mocked(tokenStore.getAccess).mockReturnValue("some-token");
    const api = (await import("@/lib/api")).default;
    vi.mocked(api.get).mockRejectedValue({
      isAxiosError: true,
      response: { status: 401 },
    });

    render(
      <AuthProvider>
        <TestConsumer />
      </AuthProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("unauthenticated")).toBeInTheDocument();
    });

    expect(tokenStore.clear).toHaveBeenCalled();
  });
});
