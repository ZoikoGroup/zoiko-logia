import { redirect } from "next/navigation";

// Syllabus mapping is now a tab in Accounting Ontology.
export default function Page() {
  redirect("/accounting-ontology?tab=syllabus");
}
