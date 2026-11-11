import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

export const getRouter = () => {
  // One client per request: a module-level QueryClient leaks cached data between SSR requests.
  // At most one retry, and never when Discord asked PEAK to slow down: retrying is what extends a block.
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: (count, error) => count < 1 && !/slow down|paused|limit|rate/i.test((error as Error)?.message ?? ""),
      },
    },
  });

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    // Lets Query own freshness; set caching defaults on the QueryClient, not the router.
    defaultPreloadStaleTime: 0,
  });

  return router;
};
