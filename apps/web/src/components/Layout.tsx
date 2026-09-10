import { useQuery } from "@tanstack/react-query";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { api, currentUser, currentRole, DEMO_USERS, setCurrentUser } from "../lib/api";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function Layout() {
  const nav = useNavigate();
  const loc = useLocation();
  const status = useQuery({ queryKey: ["system"], queryFn: api.system });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const projectId = projects.data?.[0]?.id ?? "proj_orion_ev";

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar projectId={projectId} />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar
          status={status.data}
          role={currentRole()}
          user={DEMO_USERS.find((u) => u.id === currentUser())?.name ?? currentUser()}
          onUserChange={(id) => {
            setCurrentUser(id);
            nav(loc.pathname, { replace: true });
            window.location.reload();
          }}
        />
        <main className="flex-1 min-h-0 overflow-hidden blueprint-bg">
          <Outlet context={{ projectId }} />
        </main>
      </div>
    </div>
  );
}
