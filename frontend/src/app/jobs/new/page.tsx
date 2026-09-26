import type { Metadata } from "next";
import { NewJobView } from "./NewJobView";

export const metadata: Metadata = { title: "Add a job" };

export default function NewJobPage() {
  return <NewJobView />;
}
