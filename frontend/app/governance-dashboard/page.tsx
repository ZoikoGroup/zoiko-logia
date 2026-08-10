import { redirect } from "next/navigation";

export default function LegacyGovernanceDashboardPage() {
  redirect("/overview/governance");
}
