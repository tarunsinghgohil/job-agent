import type { Metadata } from "next";
import { AnswersView } from "./AnswersView";

export const metadata: Metadata = { title: "Answer bank" };

export default function AnswersPage() {
  return <AnswersView />;
}
