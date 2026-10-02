"use client";

import { useEffect, useState } from "react";

/** Tracks whether a CSS media query currently matches. Starts `false` (the
 * narrower/mobile branch) on the server, since `window` doesn't exist there;
 * the client's first render then computes the real value via a lazy
 * `useState` initializer (not a setState call inside the effect -- this
 * project's eslint rejects that, see feedback-react-no-setstate-in-effect).
 * The effect only subscribes to further changes. Needed whenever a
 * component must mount ONE of two different element trees per breakpoint
 * (not just CSS-hide one) -- e.g. to avoid duplicate accessible text when
 * the two branches would otherwise render the same inner component twice. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(
    () => typeof window !== "undefined" && window.matchMedia(query).matches
  );

  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [query]);

  return matches;
}
