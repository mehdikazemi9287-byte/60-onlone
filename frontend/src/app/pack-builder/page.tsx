import { redirect } from "next/navigation";
// The Pack Builder lives on the homepage at #pack-builder (its original
// location). This path only redirects there so older links keep working.
export default function PackBuilderRedirect() {
  redirect("/#pack-builder");
}
