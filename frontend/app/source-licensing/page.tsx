import { redirect } from "next/navigation";

// Source Licensing is now a tab in Source Library.
export default function Page() {
  redirect("/source-library?tab=licensing");
}
