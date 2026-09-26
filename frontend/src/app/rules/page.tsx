import type { Metadata } from "next";
import { RulesView } from "./RulesView";

export const metadata: Metadata = { title: "Match rules" };

export default function RulesPage() {
  return <RulesView />;
}
