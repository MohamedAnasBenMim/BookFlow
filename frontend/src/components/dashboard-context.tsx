"use client";

import { createContext, useContext } from "react";
import type { Me, Membership } from "@/lib/api";

export type DashboardCtx = { me: Me; membership: Membership };
export const DashboardContext = createContext<DashboardCtx | null>(null);
export const useDashboard = () => useContext(DashboardContext)!;
