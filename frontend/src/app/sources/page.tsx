import type { Metadata } from "next";
import { SourcesView } from "./SourcesView";

export const metadata: Metadata = { title: "Job sources" };

export default function SourcesPage() {
  return <SourcesView />;
}
