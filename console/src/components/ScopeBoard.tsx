import { useLive } from "../context";
import { ago } from "../format";
import { useNow } from "../hooks";
import { ASSET_STATUS } from "../labels";
import type { AssetStatus } from "../types";
import { Empty, NoData } from "./Empty";
import { AssetChip } from "./Status";

export function ScopeBoard() {
  const { snapshot, connection } = useLive();
  const now = useNow(5000);
  const assets = (snapshot?.assets ?? [])
    .slice()
    .sort((a, b) => ASSET_STATUS[a.status].rank - ASSET_STATUS[b.status].rank || a.name.localeCompare(b.name));

  const tally = new Map<AssetStatus, number>();
  for (const a of assets) tally.set(a.status, (tally.get(a.status) ?? 0) + 1);

  return (
    <section className="panel" aria-labelledby="scope-h">
      <div className="panel-head">
        <h2 id="scope-h">Scope</h2>
        {assets.length > 0 && (
          <div className="scope-tally">
            {[...tally.entries()]
              .sort((a, b) => ASSET_STATUS[a[0]].rank - ASSET_STATUS[b[0]].rank)
              .map(([s, n]) => (
                <span key={s} className={`chip t-${ASSET_STATUS[s].tone}`} title={ASSET_STATUS[s].label}>
                  <span className="glyph" aria-hidden>{ASSET_STATUS[s].glyph}</span>
                  {n}
                  <span className="sr-only">{ASSET_STATUS[s].label}</span>
                </span>
              ))}
          </div>
        )}
      </div>
      {!snapshot ? (
        <NoData connection={connection} what="Asset status" />
      ) : assets.length === 0 ? (
        <Empty title="No assets reported">The backend has not listed any protected assets yet.</Empty>
      ) : (
        <ul className="assets">
          {assets.map((a) => (
            <li key={a.id} className={`asset t-${ASSET_STATUS[a.status].tone}`}>
              <details open={a.status === "exfiltrated"}>
                <summary className="row">
                  <span className="name">{a.name}</span>
                  <AssetChip status={a.status} />
                </summary>
                <span className="desc">
                  {a.description} <span className="ref mono">{a.ref}</span>
                </span>
                {a.note ? (
                  <span className="note">
                    {a.note} ({ago(a.statusSince, now)})
                  </span>
                ) : (
                  <span className="ref">Since {ago(a.statusSince, now)}</span>
                )}
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
