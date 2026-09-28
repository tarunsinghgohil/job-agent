"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { PageHeader } from "../../components/PageHeader";
import { HuntBoardView } from "./HuntBoardView";
import { HuntRunsView } from "./HuntRunsView";
import { HuntSetupView } from "./HuntSetupView";

const TABS = [
  { key: "shortlist", label: "Shortlist" },
  { key: "setup", label: "Setup" },
  { key: "runs", label: "Run history" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function HuntView() {
  const router = useRouter();
  const params = useSearchParams();
  const raw = params.get("tab");
  const tab: TabKey = TABS.some((t) => t.key === raw) ? (raw as TabKey) : "shortlist";

  function go(key: TabKey) {
    const next = new URLSearchParams(params.toString());
    next.set("tab", key);
    router.push(`/hunt?${next.toString()}`);
  }

  return (
    <>
      <PageHeader
        title="3x Job Hunt"
        description="Searches with many query variations, then ranks every job by your location priorities, experience, skills and freshness into an actionable shortlist."
      />
      <div className="tabs" role="tablist" aria-label="Job hunt">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`hunt-tab-${t.key}`}
            aria-selected={tab === t.key}
            aria-controls={`hunt-panel-${t.key}`}
            className={`tab ${tab === t.key ? "is-active" : ""}`.trim()}
            onClick={() => go(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`hunt-panel-${tab}`} aria-labelledby={`hunt-tab-${tab}`}>
        {tab === "shortlist" && <HuntBoardView />}
        {tab === "setup" && <HuntSetupView />}
        {tab === "runs" && <HuntRunsView />}
      </div>
    </>
  );
}
