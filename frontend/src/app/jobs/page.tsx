import type { Metadata } from "next";
import { Suspense } from "react";
import { JobsView } from "./JobsView";

export const metadata: Metadata = { title: "Jobs" };

export default function JobsPage() {
  return (
    <Suspense>
      <JobsView />
    </Suspense>
  );
}
