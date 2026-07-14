import { create } from "zustand";
import { persist } from "zustand/middleware";

interface OrgState {
  // Organización activa; null = modo personal (no se envía X-Org-Id).
  activeOrgId: string | null;
  activeOrgName: string | null;
  setActiveOrg: (id: string | null, name: string | null) => void;
}

export const useOrg = create<OrgState>()(
  persist(
    (set) => ({
      activeOrgId: null,
      activeOrgName: null,
      setActiveOrg: (id, name) => set({ activeOrgId: id, activeOrgName: name }),
    }),
    { name: "agentforge-org" },
  ),
);
