import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router";
import { getAccountHealth, listAccounts } from "../api.ts";
import { parseId } from "../route-params.ts";
import NotFound from "../shell/NotFound.tsx";
import type { Account, AccountHealth } from "../types.ts";
import { MEDIA_MD_UP } from "../ui/breakpoints.ts";
import Button from "../ui/Button.tsx";
import EmptyState from "../ui/EmptyState.tsx";
import ErrorState from "../ui/ErrorState.tsx";
import Skeleton from "../ui/Skeleton.tsx";
import { useMediaQuery } from "../ui/useMediaQuery.ts";
import { toApiError } from "../utils.ts";
import AccountCard from "./accounts/AccountCard.tsx";
import AccountDetail from "./accounts/AccountDetail.tsx";
import AddAccountSheet from "./accounts/AddAccountSheet.tsx";
import "./accounts/accounts.css";
import { useProject } from "./project-context.ts";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; health: AccountHealth[]; accounts: Account[] };

/**
 * /p/:projectId/accounts[/new | /:accountId]: account health at a glance, the
 * Add account sheet and the account detail, all chosen by the URL. The list
 * stays mounted behind them.
 */
function AccountsPage() {
  const { project, reloadOverview } = useProject();
  const { accountId } = useParams();
  const adding = accountId === "new";
  const selectedId =
    accountId === undefined || adding ? null : parseId(accountId);
  const isMedium = useMediaQuery(MEDIA_MD_UP);
  const [state, setState] = useState<LoadState>({ status: "loading" });
  // Just deleted: its URL may still be current for a render while the
  // navigation away is applied (a transition), never "Not found".
  const [deletedId, setDeletedId] = useState<number | null>(null);
  const base = `/p/${project.id}/accounts`;

  const load = useCallback(
    () =>
      Promise.all([getAccountHealth(project.id), listAccounts(project.id)])
        .then(([health, accounts]) =>
          setState({ status: "loaded", health, accounts }),
        )
        .catch((caught: unknown) =>
          setState({ status: "error", message: toApiError(caught).message }),
        ),
    [project.id],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const handleChanged = useCallback(() => {
    reloadOverview();
    return load();
  }, [load, reloadOverview]);

  if (accountId !== undefined && !adding && selectedId === null) {
    return <NotFound backTo={{ to: base, label: "Back to Accounts" }} />;
  }
  const loaded = state.status === "loaded" ? state : null;
  const selectedHealth = loaded?.health.find(
    (item) => item.account_id === selectedId,
  );
  const selectedAccount = loaded?.accounts.find(
    (item) => item.id === selectedId,
  );
  // Another project's account, or one that does not exist.
  if (
    loaded &&
    selectedId !== null &&
    selectedId !== deletedId &&
    (!selectedHealth || !selectedAccount)
  ) {
    return <NotFound backTo={{ to: base, label: "Back to Accounts" }} />;
  }

  const showingDetail =
    selectedHealth !== undefined && selectedAccount !== undefined;
  const active = loaded?.health.filter((item) => item.is_active) ?? [];
  const inactive = loaded?.health.filter((item) => !item.is_active) ?? [];

  return (
    <div
      className={
        showingDetail ? "ap-accounts ap-accounts--with-detail" : "ap-accounts"
      }
    >
      {/* Hidden, not unmounted, behind a phone's full-page detail. */}
      <div className="ap-accounts__list" hidden={showingDetail && !isMedium}>
        <div className="ap-accounts__header ap-page-header">
          <h1 className="ap-page-title">Accounts</h1>
          {project.is_active && loaded && loaded.health.length > 0 && (
            <Button as="link" to={`${base}/new`} icon="plus">
              Add account
            </Button>
          )}
        </div>
        {!project.is_active && (
          <p className="ap-meta">Reactivate this project to add accounts.</p>
        )}

        {state.status === "loading" && (
          <Skeleton lines={4} label="Loading accounts…" />
        )}
        {state.status === "error" && (
          <ErrorState
            title="Couldn't load the accounts"
            message={state.message}
            onRetry={() => void load()}
          />
        )}
        {loaded && loaded.health.length === 0 && project.is_active && (
          <EmptyState
            title="Connect an account"
            description="Connect the accounts this project publishes to."
            action={
              <Button
                as="link"
                to={`${base}/new`}
                variant="primary"
                icon="plus"
              >
                Connect an account
              </Button>
            }
          />
        )}
        {active.length > 0 && (
          <ul className="ap-account-list" aria-label="Accounts">
            {active.map((item) => (
              <AccountCard
                key={item.account_id}
                health={item}
                to={`${base}/${item.account_id}`}
                selected={item.account_id === selectedId}
              />
            ))}
          </ul>
        )}
        {inactive.length > 0 && (
          <section aria-labelledby="accounts-inactive">
            <h2
              id="accounts-inactive"
              className="ap-section-title ap-accounts__subtitle"
            >
              Inactive
            </h2>
            <ul className="ap-account-list" aria-label="Inactive accounts">
              {inactive.map((item) => (
                <AccountCard
                  key={item.account_id}
                  health={item}
                  to={`${base}/${item.account_id}`}
                  selected={item.account_id === selectedId}
                />
              ))}
            </ul>
          </section>
        )}
      </div>

      {showingDetail && (
        <AccountDetail
          key={selectedAccount.id}
          project={project}
          health={selectedHealth}
          account={selectedAccount}
          onChanged={handleChanged}
          onDeleted={() => {
            setDeletedId(selectedAccount.id);
            void handleChanged();
          }}
        />
      )}
      {adding && (
        <AddAccountSheet project={project} onChanged={handleChanged} />
      )}
    </div>
  );
}

export default AccountsPage;
