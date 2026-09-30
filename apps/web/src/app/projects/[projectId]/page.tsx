"use client";

import { useParams } from "next/navigation";
import { AuthGate } from "@/components/auth/auth-gate";
import { ProjectWorkspace } from "@/components/workspace/project-workspace";

export default function ProjectWorkspacePage() {
  const params = useParams<{ projectId: string }>();
  return <AuthGate><ProjectWorkspace projectId={params.projectId} /></AuthGate>;
}
