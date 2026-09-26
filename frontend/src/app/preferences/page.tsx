import type { Metadata } from "next";
import { PreferencesView } from "./PreferencesView";

export const metadata: Metadata = { title: "Preferences" };

export default function PreferencesPage() {
  return <PreferencesView />;
}
