import {
  platformLabel,
  type AccountHealth,
  type Capability,
} from "../../types.ts";

const CAPABILITY_LABELS: Record<Capability, string> = {
  text: "Text",
  images: "Images",
  videos: "Videos",
};

export function capabilitiesText(capabilities: Capability[]): string {
  return capabilities
    .map((capability) => CAPABILITY_LABELS[capability])
    .join(" · ");
}

/** Who the account is: the connected identity, else what AutoPublisher knows. */
export function identityText(health: AccountHealth): string {
  if (health.identity) {
    return health.identity.username
      ? `@${health.identity.username}`
      : health.identity.name;
  }
  return health.state === "not_connected" ? "Not connected yet" : health.label;
}

export function accountTitle(health: AccountHealth): string {
  return `${platformLabel(health.platform)} ${identityText(health)}`;
}

/** The one action an account needs, if any (Ready and Inactive need none). */
export function primaryAction(health: AccountHealth): string | null {
  switch (health.state) {
    case "reconnect_needed":
      return "Reconnect";
    case "setup_required":
      return "Finish setup";
    case "not_connected":
      return "Connect";
    case "ready":
      return health.expiring ? "Reconnect" : null;
    case "inactive":
      return null;
  }
}
