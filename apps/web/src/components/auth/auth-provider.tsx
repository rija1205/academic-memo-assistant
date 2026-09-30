"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  getCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  register as registerRequest,
  type AuthUser,
} from "@/lib/api";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<AuthUser>;
  register: (email: string, password: string, displayName?: string) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const requestVersion = useRef(0);

  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    try {
      const currentUser = await getCurrentUser();
      if (version === requestVersion.current) {
        setUser(currentUser);
      }
    } catch {
      if (version === requestVersion.current) {
        setUser(null);
      }
    } finally {
      if (version === requestVersion.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const version = ++requestVersion.current;
    const response = await loginRequest({ email, password });
    if (version === requestVersion.current) {
      setUser(response.user);
      setLoading(false);
    }
    return response.user;
  }, []);

  const register = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const version = ++requestVersion.current;
      const response = await registerRequest({
        email,
        password,
        display_name: displayName,
      });
      if (version === requestVersion.current) {
        setUser(response.user);
        setLoading(false);
      }
      return response.user;
    },
    [],
  );

  const logout = useCallback(async () => {
    await logoutRequest();
    requestVersion.current += 1;
    setUser(null);
    setLoading(false);
    router.push("/login");
  }, [router]);

  const value = useMemo(
    () => ({ user, loading, login, register, logout, refresh }),
    [user, loading, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider.");
  return context;
}
