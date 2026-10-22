// Session = who is acting. The role switcher changes it; every API call then
// carries the new identity, and all cached data is dropped so nothing fetched
// under one role (e.g. unmasked identifiers) is shown under another.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setActorHeader, type Actor } from "./api/client";

const STORAGE_KEY = "workpaper.actor";

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

interface Session {
  actor: Actor | null;
  actors: Actor[];
  setActor: (id: string) => void;
}

const SessionContext = createContext<Session>({ actor: null, actors: [], setActor: () => {} });

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [actorId, setActorId] = useState<string | null>(() => {
    const stored = readStored();
    setActorHeader(stored);
    return stored;
  });
  // The roster is identity metadata, not workpaper data: fetched without an actor header.
  const roster = useQuery({ queryKey: ["actors"], queryFn: api.actors, staleTime: Infinity });

  const actors = roster.data ?? [];
  const fallback = actors.find((a) => a.assignments.includes("preparer")) ?? actors[0] ?? null;
  const actor = actors.find((a) => a.id === actorId) ?? fallback;

  // A stored id that is no longer on the roster falls back to the assigned preparer.
  useEffect(() => {
    if (roster.data && actorId && !roster.data.some((a) => a.id === actorId)) {
      setActorHeader(fallback?.id ?? null);
      setActorId(fallback?.id ?? null);
    }
  }, [roster.data, actorId, fallback]);

  const setActor = useCallback((id: string) => {
    setActorHeader(id);
    setActorId(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* private mode: switch still works for this tab */
    }
    const notRoster = (q: { queryKey: readonly unknown[] }) => q.queryKey[0] !== "actors";
    if (roster.data?.find((a) => a.id === id)?.kind === "client") {
      // A client sees a different shell: drop firm data without refetching it under the client identity.
      void queryClient.cancelQueries({ predicate: notRoster });
      queryClient.removeQueries({ predicate: notRoster });
    } else {
      // Staff to staff: reset everything fetched under the previous identity (active
      // queries refetch at once with the new header, so no unmasked data lingers).
      void queryClient.resetQueries({ predicate: notRoster });
    }
  }, [queryClient, roster.data]);

  const value = useMemo(() => ({ actor, actors, setActor }), [actor, actors, setActor]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  return useContext(SessionContext);
}
