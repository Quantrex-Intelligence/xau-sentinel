import { redirect } from "next/navigation";

/** The Market page is the single place for setup, analysis and market reading. Old routes forward to it. */
export default function Home() {
  redirect("/market");
}
