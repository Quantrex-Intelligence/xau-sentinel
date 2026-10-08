import { redirect } from "next/navigation";

/** Folded into the unified Market page. Kept so old links still open the right place. */
export default function Redirect() {
  redirect("/market");
}
