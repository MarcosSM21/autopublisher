import type { ReactNode } from "react";
import { NavLink } from "react-router";
import Icon, { type IconName } from "../ui/Icon.tsx";
import { PROJECT_SECTIONS, type ProjectSection } from "./useProjectTarget.ts";

const SECTION_LABELS: Record<ProjectSection, string> = {
  library: "Library",
  posts: "Posts",
  accounts: "Accounts",
};

interface PrimaryNavProps {
  /** Project the project destinations open; null disables them. */
  projectId: number | null;
  /** Rendered after Home (the `lg` sidebar places the project selector there). */
  projectSelector?: ReactNode;
}

function navClass({ isActive }: { isActive: boolean }) {
  return isActive ? "ap-nav__item ap-nav__item--active" : "ap-nav__item";
}

/**
 * The only main navigation. One DOM for every breakpoint: CSS lays it out as
 * sidebar (`lg`), rail (`md`) or fixed bottom bar (`sm`, where Settings lives in
 * the TopBar's "More"). NavLink sets aria-current="page" on the active item.
 */
function PrimaryNav({ projectId, projectSelector }: PrimaryNavProps) {
  return (
    <nav aria-label="Main" className="ap-nav">
      <p className="ap-nav__brand">
        <span className="ap-mark" aria-hidden="true" />
        AutoPublisher
      </p>
      <ul className="ap-nav__list">
        <li>
          <NavLink to="/" end className={navClass}>
            <Icon name="home" />
            Home
          </NavLink>
        </li>
        {projectSelector && (
          <li className="ap-nav__selector">{projectSelector}</li>
        )}
        {PROJECT_SECTIONS.map((section) => (
          <li key={section}>
            {projectId !== null ? (
              <NavLink to={`/p/${projectId}/${section}`} className={navClass}>
                <Icon name={section as IconName} />
                {SECTION_LABELS[section]}
              </NavLink>
            ) : (
              <span
                className="ap-nav__item ap-nav__item--disabled"
                aria-disabled="true"
              >
                <Icon name={section as IconName} />
                {SECTION_LABELS[section]}
              </span>
            )}
          </li>
        ))}
        <li className="ap-nav__settings">
          <NavLink to="/settings" className={navClass}>
            <Icon name="settings" />
            Settings
          </NavLink>
        </li>
      </ul>
    </nav>
  );
}

export default PrimaryNav;
