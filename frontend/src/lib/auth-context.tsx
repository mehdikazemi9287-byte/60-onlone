"use client";
import { bindDraftOwner, clearDraftOwner } from "@/lib/client-draft-storage";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { auth, type AuthUser, ApiError } from "@/lib/api";

const TOKEN_KEY = "60online_token";

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithOtp: (phone: string, code: string, fullName?: string, acceptTerms?: boolean) => Promise<{ created: boolean }>;
  register: (email: string, password: string, fullName: string, phone?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive=true, generation=0;
    const read=()=>{try{return localStorage.getItem(TOKEN_KEY);}catch{return null;}};
    const refresh=()=>{
      const version=++generation, stored=read();
      clearDraftOwner(); setToken(null); setUser(null); setLoading(!!stored);
      if(!stored)return;
      auth.me(stored).then(res=>{
        if(alive && version===generation && read()===stored){bindDraftOwner(res.user.id);setToken(stored);setUser(res.user);}
      }).catch(err=>{
        // A transient outage must not destroy a valid stored session.
        if(err instanceof ApiError && err.status===401 && read()===stored)
          try{localStorage.removeItem(TOKEN_KEY);}catch{}
      }).finally(()=>{if(alive && version===generation)setLoading(false);});
    };
    const storage=(event:StorageEvent)=>{if(event.storageArea===localStorage && (event.key===TOKEN_KEY || event.key===null))refresh();};
    const invalid=(event:Event)=>{
      const expired=(event as CustomEvent<string>).detail;
      if(expired && read()===expired){try{localStorage.removeItem(TOKEN_KEY);}catch{} refresh();}
    };
    refresh();
    window.addEventListener("storage",storage);
    window.addEventListener("60online:session-invalid",invalid);
    return ()=>{alive=false;generation++;window.removeEventListener("storage",storage);window.removeEventListener("60online:session-invalid",invalid);};
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await auth.login(email, password);
    localStorage.setItem(TOKEN_KEY, res.access_token);
    bindDraftOwner(res.user.id);
    setToken(res.access_token);
    setUser(res.user);
  }, []);

  const loginWithOtp = useCallback(async (phone: string, code: string, fullName?: string, acceptTerms?: boolean) => {
    const res = await auth.otpVerify(phone, code, fullName, acceptTerms);
    localStorage.setItem(TOKEN_KEY, res.access_token);
    bindDraftOwner(res.user.id);
    setToken(res.access_token);
    setUser(res.user);
    return { created: res.created };
  }, []);

  const register = useCallback(
    async (email: string, password: string, fullName: string, phone?: string) => {
      const res = await auth.register(email, password, fullName, phone);
      localStorage.setItem(TOKEN_KEY, res.access_token);
      bindDraftOwner(res.user.id);
    setToken(res.access_token);
      setUser(res.user);
    },
    []
  );

  const logout = useCallback(() => {
    const t = token;
    clearDraftOwner();
    try { localStorage.removeItem(TOKEN_KEY); } catch {}
    setToken(null);
    setUser(null);
    if (t) auth.logout(t).catch(() => {});
  }, [token]);

  return (
    <AuthContext.Provider value={{ user, token, loading, login, loginWithOtp, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export { ApiError };
