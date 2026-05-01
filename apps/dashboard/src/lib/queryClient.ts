import { QueryClient } from "@tanstack/react-query";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Live data also arrives via WebSocket — REST is for initial load + history.
        staleTime: 5 * 1000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}
