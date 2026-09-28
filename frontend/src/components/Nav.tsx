"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "../lib/auth";

interface NavItem {
  href: string;
  label: string;
  group: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Overview", group: "Work" },
  { href: "/hunt", label: "Job hunt", group: "Work" },
  { href: "/jobs", label: "Jobs", group: "Work" },
  { href: "/applications", label: "Applications", group: "Work" },
  { href: "/analytics", label: "Analytics", group: "Work" },
  { href: "/resumes", label: "Resumes", group: "Career brain" },
  { href: "/answers", label: "Answer bank", group: "Career brain" },
  { href: "/profile", label: "Profile", group: "Career brain" },
  { href: "/preferences", label: "Preferences", group: "Policy" },
  { href: "/rules", label: "Match rules", group: "Policy" },
  { href: "/sources", label: "Job sources", group: "Policy" },
  { href: "/automations", label: "Automations", group: "Operations" },
  { href: "/integrations", label: "Integrations", group: "Operations" },
  { href: "/notifications", label: "Notifications", group: "Operations" },
  { href: "/settings", label: "Settings", group: "Operations" },
];

const GROUPS = ["Work", "Career brain", "Policy", "Operations"];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Nav() {
  const pathname = usePathname() || "/";
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        className="nav-toggle"
        aria-expanded={open}
        aria-controls="primary-nav"
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">☰</span>
        <span>Menu</span>
      </button>
      <aside
        id="primary-nav"
        className={`sidebar ${open ? "is-open" : ""}`.trim()}
      >
        <Link href="/" className="brand-link">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              JA
            </span>
            <span className="brand-text">
              <strong>Job Agent</strong>
              <small>Career operations</small>
            </span>
          </div>
        </Link>

        <nav className="nav" aria-label="Primary">
          {GROUPS.map((group) => (
            <div className="nav-group" key={group}>
              <p className="nav-group-title">{group}</p>
              <ul>
                {NAV_ITEMS.filter((item) => item.group === group).map(
                  (item) => (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className={
                          isActive(pathname, item.href)
                            ? "nav-link is-active"
                            : "nav-link"
                        }
                        aria-current={
                          isActive(pathname, item.href) ? "page" : undefined
                        }
                        onClick={() => setOpen(false)}
                      >
                        {item.label}
                      </Link>
                    </li>
                  ),
                )}
              </ul>
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="sidebar-user">
            <strong>{user?.full_name || user?.email || "Signed in"}</strong>
            {user?.email && user.full_name ? <small>{user.email}</small> : null}
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => void logout()}
          >
            <span>Sign out</span>
          </button>
        </div>
      </aside>
    </>
  );
}
