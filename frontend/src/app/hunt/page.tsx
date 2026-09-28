import type { Metadata } from "next";
import { Suspense } from "react";
import { HuntView } from "./HuntView";

export const metadata: Metadata = { title: "Job hunt" };

export default function HuntPage() {
  return (
    <Suspense>
      <HuntView />
    </Suspense>
  );
}
