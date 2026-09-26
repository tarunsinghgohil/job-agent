import type { Metadata } from "next";
import { ApplicationDetailView } from "./ApplicationDetailView";

export const metadata: Metadata = { title: "Application" };

export default async function ApplicationDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ApplicationDetailView applicationId={id} />;
}
