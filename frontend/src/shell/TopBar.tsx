import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router";
import Disclosure from "../ui/Disclosure.tsx";
import Icon from "../ui/Icon.tsx";

interface TopBarProps {
  projectSelector: ReactNode;
  /** `sm` only: Settings does not fit the bottom navigation. */
  showMore: boolean;
}

/** Top bar of `sm` and `md`: the project selector and, on phones, "More". */
function TopBar({ projectSelector, showMore }: TopBarProps) {
  const { pathname } = useLocation();
  return (
    <header className="ap-topbar">
      {projectSelector}
      {showMore && (
        // Keyed by URL: following a link inside closes the region.
        <Disclosure
          key={pathname}
          className={
            // Settings is behind "More" on phones: show where the user is.
            pathname.startsWith("/settings")
              ? "ap-menu ap-topbar__more ap-topbar__more--current"
              : "ap-menu ap-topbar__more"
          }
          label={
            <>
              <Icon name="more" />
              More
            </>
          }
        >
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              isActive ? "ap-nav__item ap-nav__item--active" : "ap-nav__item"
            }
          >
            <Icon name="settings" />
            Settings
          </NavLink>
        </Disclosure>
      )}
    </header>
  );
}

export default TopBar;
