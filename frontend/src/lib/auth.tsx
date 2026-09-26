"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  ApiError,
  refreshAccessToken,
  setAccessToken,
  setUnauthenticatedHandler,
} from "./api";
import type { LoginResponse, User } from "./types";

interface AuthContextValue {
  user: User | null;
  /** True until the initial cookie-based refresh has been attempted. */
  initializing: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<boolean>;
  setUser: (user: User) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [initializing, setInitializing] = useState(true);
  const router = useRouter();
  const bootstrapped = useRef(false);

  const clear = useCallback(() => {
    setAccessToken(null);
    setUserState(null);
  }, []);

  const refresh = useCallback(async (): Promise<boolean> => {
    const token = await refreshAccessToken();
    if (!token) {
      clear();
      return false;
    }
    try {
      const me = await api.get<User>("/api/v1/auth/me");
      setUserState(me);
      return true;
    } catch {
      clear();
      return false;
    }
  }, [clear]);

  // A silent refresh on mount is what turns the httpOnly cookie into a session
  // without ever putting a token in localStorage.
  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    void refresh().finally(() => setInitializing(false));
  }, [refresh]);

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      clear();
      router.replace("/login");
    });
    return () => setUnauthenticatedHandler(null);
  }, [clear, router]);

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await api.post<LoginResponse>("/api/v1/auth/login", { email, password });
      if (!result?.access_token) {
        throw new ApiError(500, "bad_response", "The server did not return an access token.");
      }
      setAccessToken(result.access_token);
      setUserState(result.user);
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api.post<void>("/api/v1/auth/logout");
    } catch {
      // A failed revoke must not trap the user in a signed-in shell.
    }
    clear();
    router.replace("/login");
  }, [clear, router]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, initializing, login, logout, refresh, setUser: setUserState }),
    [user, initializing, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>.");
  return context;
}
