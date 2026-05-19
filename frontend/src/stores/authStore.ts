import { create } from "zustand";
import { apiClient } from "../api/client";

interface AuthState {
  token: string | null;
  user: { id: number; username: string; role: string } | null;
  initialized: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  init: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  user: null,
  initialized: false,

  login: async (username: string, password: string) => {
    const resp = await apiClient.post("/auth/login", { username, password });
    const { token, user } = resp.data.data;
    localStorage.setItem("token", token);
    set({ token, user, initialized: true });
  },

  logout: () => {
    const token = get().token;
    if (token) {
      apiClient.post("/auth/logout").catch(() => {});
    }
    localStorage.removeItem("token");
    set({ token: null, user: null });
  },

  init: () => {
    const token = localStorage.getItem("token");
    if (token) {
      set({ token, initialized: true });
      // Fetch user info
      apiClient.get("/auth/me")
        .then((resp) => set({ user: resp.data.data }))
        .catch(() => { localStorage.removeItem("token"); set({ token: null }); });
    } else {
      set({ initialized: true });
    }
  },
}));

import { configureAuth } from "../api/client";

// Wire up auth token to API client
useAuthStore.subscribe((state) => {
  configureAuth(
    () => state.token,
    () => useAuthStore.getState().logout()
  );
});
