import type { Metadata } from "next";
import { ResumesView } from "./ResumesView";

export const metadata: Metadata = { title: "Resumes" };

export default function ResumesPage() {
  return <ResumesView />;
}
