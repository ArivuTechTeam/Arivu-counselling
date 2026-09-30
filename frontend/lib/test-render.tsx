import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { SWRConfig } from "swr";

/**
 * Render with a fresh, empty SWR cache. SWR caches by key across renders, so
 * without this one test's data would leak into the next.
 */
export function renderWithSWR(ui: ReactElement) {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>,
  );
}
