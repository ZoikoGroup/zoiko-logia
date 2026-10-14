import { redirect } from "next/navigation";

// Professional Boundaries is now a tab in Risk Policy.
export default function Page() {
  redirect("/risk-policy?tab=boundaries");
}
