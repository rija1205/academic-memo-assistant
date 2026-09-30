"use client";

import { AuthGate } from "@/components/auth/auth-gate";
import { AdminWorkspace } from "@/components/admin/admin-workspace";

export default function AdminPage() {
  return (
    <AuthGate>
      <div className="admin-shell">
        <header className="admin-topbar">
          <div>
            <strong>Administration</strong>
            <span>Academic Memo Assistant</span>
          </div>
        </header>
        <AdminWorkspace />
      </div>
    </AuthGate>
  );
}
