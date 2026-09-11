import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { ReactNode } from "react";
import { vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

/**
 * Render one screen the way the app does: inside a router and a query client.
 *
 * Retries are off so a failing fetch surfaces immediately instead of after
 * three silent attempts, and each test gets its own client so cached data
 * cannot leak between them.
 */
export function renderRoute(
  element: ReactNode,
  { path = "/", route = "/" }: { path?: string; route?: string } = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

type Stub = unknown | ((body: unknown) => { status?: number; body: unknown });

/**
 * Stub `fetch` with a path → JSON map. Unmatched paths fail loudly rather than
 * returning undefined, so a test can never pass against a route it forgot.
 *
 * A route may be a function, which receives the parsed request body — that is
 * how a form test asserts on what was actually sent.
 */
export function mockApi(routes: Record<string, Stub>) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });

    const METHOD = /^(GET|POST|PATCH|PUT|DELETE) /;
    const key = Object.keys(routes)
      .filter((k) => url.startsWith(k.replace(METHOD, "")))
      .find((k) => !METHOD.test(k) || k.startsWith(`${method} `));
    if (key === undefined) {
      throw new Error(`No stub for ${method} ${url}. Stubbed: ${Object.keys(routes).join(", ")}`);
    }
    const route = routes[key];
    const resolved = typeof route === "function"
      ? (route as (b: unknown) => { status?: number; body: unknown })(body)
      : { status: 200, body: route };
    const status = resolved.status ?? 200;
    return {
      ok: status < 400,
      status,
      statusText: "OK",
      text: async () => JSON.stringify(resolved.body),
    } as Response;
  });
  return Object.assign(fetchMock, { calls });
}
