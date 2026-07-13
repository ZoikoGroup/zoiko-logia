"use client";

import { useRole } from "@/components/shell/RoleProvider";
import { PageHeader } from "@/components/governance/PageHeader";
import { RecentKritonActivityModule, allowedRoles as recentActivityRoles } from "./modules/RecentKritonActivityModule";
import { GovernanceSnapshotModule, allowedRoles as governanceRoles } from "./modules/GovernanceSnapshotModule";
import { LearningProgressModule, allowedRoles as learningRoles } from "./modules/LearningProgressModule";
import type { RoleCode } from "@/lib/roles";

const MODULES: { id: string; allowedRoles: RoleCode[]; Component: React.ComponentType }[] = [
  { id: "governance-snapshot", allowedRoles: governanceRoles, Component: GovernanceSnapshotModule },
  { id: "learning-progress", allowedRoles: learningRoles, Component: LearningProgressModule },
  { id: "recent-kriton-activity", allowedRoles: recentActivityRoles, Component: RecentKritonActivityModule },
];

export function CommandCenter() {
  const { role } = useRole();
  const visibleModules = MODULES.filter((m) => m.allowedRoles.includes(role));

  return (
    <main className="flex-1 overflow-y-auto p-4">
      <PageHeader
        title="Command Center"
        subtitle={`Composed for your current role: ${role}. Modules below change automatically as role changes.`}
      />
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {visibleModules.map(({ id, Component }) => (
          <Component key={id} />
        ))}
      </div>
    </main>
  );
}
