import { Link } from "react-router";
import { MEDIA_MD_UP } from "../../ui/breakpoints.ts";
import Disclosure from "../../ui/Disclosure.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";

export interface Crumb {
  label: string;
  /** Where an ancestor leads; the last crumb is the current page. */
  to: string;
}

/** Levels below `Library` a phone shows before collapsing the middle ones. */
const PHONE_LEVELS = 2;

/**
 * `Library / … / Folder`: every ancestor is a link, the last crumb is the
 * current page. On phones, past two levels, the ones between `Library` and the
 * current folder collapse behind a "…" button; long names truncate, so it never
 * scrolls sideways.
 */
function Breadcrumb({ items }: { items: Crumb[] }) {
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const [first, ...rest] = items;
  const current = rest.pop() ?? first;
  const collapse = !isMedium && rest.length + 1 > PHONE_LEVELS;

  return (
    <nav aria-label="Breadcrumb" className="ap-breadcrumb">
      <ol className="ap-breadcrumb__list">
        {current !== first && (
          <li className="ap-breadcrumb__item">
            <Link to={first.to} className="ap-breadcrumb__link">
              {first.label}
            </Link>
          </li>
        )}
        {collapse ? (
          <li className="ap-breadcrumb__item">
            <Disclosure
              label={
                <>
                  <span aria-hidden="true">…</span>
                  <span className="ap-visually-hidden">
                    Show {rest.length} more folders
                  </span>
                </>
              }
              className="ap-menu ap-breadcrumb__more"
            >
              <ul className="ap-breadcrumb__hidden">
                {rest.map((crumb) => (
                  <li key={crumb.to}>
                    <Link to={crumb.to}>{crumb.label}</Link>
                  </li>
                ))}
              </ul>
            </Disclosure>
          </li>
        ) : (
          rest.map((crumb) => (
            <li key={crumb.to} className="ap-breadcrumb__item">
              <Link to={crumb.to} className="ap-breadcrumb__link">
                {crumb.label}
              </Link>
            </li>
          ))
        )}
        <li className="ap-breadcrumb__item">
          <span className="ap-breadcrumb__current" aria-current="page">
            {current.label}
          </span>
        </li>
      </ol>
    </nav>
  );
}

export default Breadcrumb;
