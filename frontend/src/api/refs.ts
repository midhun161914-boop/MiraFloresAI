// Reference resolution for chips. A screen can render hundreds of RefChips;
// instead of one request each, lookups made in the same tick are coalesced into
// a single POST /api/resolve/batch, and React Query caches every result.
import { useQuery } from "@tanstack/react-query";
import { api, type RefResolution } from "./client";

type Pending = { resolve: (r: RefResolution) => void; reject: (e: unknown) => void };
const queue = new Map<string, Pending[]>();
let scheduled = false;

function flush() {
  scheduled = false;
  const batch = new Map(queue);
  queue.clear();
  const refs = [...batch.keys()];
  api.resolveBatch(refs).then(
    (results) => {
      results.forEach((r, i) => batch.get(refs[i])?.forEach((p) => p.resolve(r)));
    },
    (err) => batch.forEach((ps) => ps.forEach((p) => p.reject(err))),
  );
}

export function resolveBatched(ref: string): Promise<RefResolution> {
  return new Promise((resolve, reject) => {
    const list = queue.get(ref) ?? [];
    list.push({ resolve, reject });
    queue.set(ref, list);
    if (!scheduled) {
      scheduled = true;
      setTimeout(flush, 0);
    }
  });
}

export function useResolvedRef(ref: string) {
  return useQuery({
    queryKey: ["ref", ref],
    queryFn: () => resolveBatched(ref),
    staleTime: Infinity, // the packet is immutable for the life of the server
  });
}
