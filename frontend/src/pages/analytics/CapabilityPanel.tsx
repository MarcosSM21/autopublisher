import type { AccountCapability } from "../../types.ts";
import Badge from "../../ui/Badge.tsx";
import Card from "../../ui/Card.tsx";
import { CAPABILITY } from "./copy.ts";

const GROUP_LABELS: Record<string, string> = {
  basic: "Public counters",
  insights: "Insights",
};

interface CapabilityPanelProps {
  accounts: AccountCapability[];
}

/** One row per account: what AutoPublisher can read and what is missing. */
function CapabilityPanel({ accounts }: CapabilityPanelProps) {
  return (
    <Card as="section" aria-labelledby="analytics-accounts">
      <h2 id="analytics-accounts" className="ap-section-title">
        What each account can show
      </h2>
      <ul className="ap-analytics__capabilities">
        {accounts.map(({ account_id, label, capability }) => {
          const appearance = CAPABILITY[capability.state];
          // Groups only add information when they differ from the account.
          const groups =
            capability.groups.length > 1
              ? capability.groups
              : capability.groups.filter((g) => g.state !== capability.state);
          return (
            <li key={account_id} className="ap-analytics__capability">
              <div className="ap-analytics__capability-head">
                <span className="ap-analytics__account">{label}</span>
                <Badge tone={appearance.tone} icon={appearance.icon}>
                  {appearance.label}
                </Badge>
              </div>
              {capability.state !== "supported" && (
                <p className="ap-meta">{appearance.description}</p>
              )}
              {groups.length > 0 && (
                <ul className="ap-analytics__groups">
                  {groups.map((group) => (
                    <li key={group.group}>
                      {GROUP_LABELS[group.group] ?? group.group}:{" "}
                      {CAPABILITY[group.state].label.toLowerCase()}
                      {group.missing_permission && (
                        <>
                          {" "}
                          (<code>{group.missing_permission}</code>)
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

export default CapabilityPanel;
