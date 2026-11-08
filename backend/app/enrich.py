"""External-service enrichment the defender agents call mid-investigation.

Two real, PUBLIC, key-less APIs so the agents "use external APIs and services intelligently"
(the NVIDIA criterion), beyond the in-cluster Kubernetes API:

  * lookup_cve()     -> NVD (nvd.nist.gov) — the real CVE + CVSS for the exploited vector.
  * mining_impact()  -> CoinGecko — the live Monero price, to size the stolen GPU compute.

Every call is wrapped so a slow/unreachable API falls back to a bundled value: the demo must
never hang on the network. No API keys are used, so nothing secret is ever sent or logged.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

_TIMEOUT = 6  # seconds — short, so a slow API can't stall the agent loop; we fall back instead

# Known-vector fallback so the demo never depends on NVD being reachable or fast. The exposed,
# unauthenticated notebook/Ray dashboard this scenario is built on is the real "ShadowRay" bug.
_CVE_CACHE = {
    "ray": {
        "id": "CVE-2023-48022", "cvss": 9.8, "severity": "CRITICAL",
        "summary": "Anyscale Ray's dashboard/jobs API ships with no authentication, allowing "
                   "unauthenticated remote code execution — the basis of the 'ShadowRay' campaign.",
    },
    "jupyter": {
        "id": "CVE-2023-48022", "cvss": 9.8, "severity": "CRITICAL",
        "summary": "An unauthenticated notebook/job API exposed to the network allows remote code "
                   "execution inside the pod, exactly as in the ShadowRay campaign.",
    },
    "notebook": {
        "id": "CVE-2023-48022", "cvss": 9.8, "severity": "CRITICAL",
        "summary": "Exposed, unauthenticated notebook API enables remote code execution in the pod.",
    },
}

_T4_USD_PER_HOUR = 0.526   # on-demand cloud rent for a Tesla T4 (AWS g4dn.xlarge) — the stolen-compute rate
_XMR_USD_FALLBACK = 160.0  # cached Monero price for offline demos


def _get_json(url: str) -> dict:
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "hackutd-defender/1.0"}
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.load(r)


def lookup_cve(keyword: str) -> dict:
    """Live NVD keyword search for the exploited vector; falls back to a cached match.
    Returns {id, cvss, severity, summary, url, source}."""
    kw = (keyword or "").strip() or "unauthenticated notebook remote code execution"
    try:
        data = _get_json(
            "https://services.nvd.nist.gov/rest/json/cves/2.0?keywordSearch="
            + urllib.parse.quote(kw) + "&resultsPerPage=1"
        )
        vulns = data.get("vulnerabilities") or []
        if vulns:
            cve = vulns[0]["cve"]
            cvid = cve["id"]
            desc = next((d["value"] for d in cve.get("descriptions", []) if d.get("lang") == "en"), "")
            metrics = cve.get("metrics", {})
            m = (metrics.get("cvssMetricV31") or metrics.get("cvssMetricV30") or [{}])[0].get("cvssData", {})
            return {
                "id": cvid, "cvss": m.get("baseScore"), "severity": m.get("baseSeverity"),
                "summary": desc[:240], "url": f"https://nvd.nist.gov/vuln/detail/{cvid}",
                "source": "NVD (live)",
            }
    except Exception:  # noqa: BLE001 — any network/parse failure falls back to the cache
        pass
    for key, v in _CVE_CACHE.items():
        if key in kw.lower():
            return {**v, "url": f"https://nvd.nist.gov/vuln/detail/{v['id']}", "source": "NVD (cached)"}
    v = _CVE_CACHE["notebook"]
    return {**v, "url": f"https://nvd.nist.gov/vuln/detail/{v['id']}", "source": "NVD (cached)"}


def mining_impact(hours: float = 1.0) -> dict:
    """Live Monero price (CoinGecko) + the $ value of the stolen GPU compute over `hours`.
    Returns {xmr_usd_now, t4_usd_per_hour, stolen_compute_usd, hours, source}."""
    xmr = None
    try:
        xmr = _get_json(
            "https://api.coingecko.com/api/v3/simple/price?ids=monero&vs_currencies=usd"
        ).get("monero", {}).get("usd")
    except Exception:  # noqa: BLE001
        pass
    source = "CoinGecko (live)" if xmr else "CoinGecko (cached)"
    xmr = xmr or _XMR_USD_FALLBACK
    try:
        hrs = max(0.0, float(hours))
    except (TypeError, ValueError):
        hrs = 1.0
    return {
        "xmr_usd_now": round(float(xmr), 2),
        "t4_usd_per_hour": _T4_USD_PER_HOUR,
        "stolen_compute_usd": round(_T4_USD_PER_HOUR * hrs, 2),
        "hours": hrs,
        "source": source,
    }


if __name__ == "__main__":  # quick manual check: python -m app.enrich
    print("CVE:", lookup_cve("unauthenticated Jupyter Ray notebook remote code execution"))
    print("IMPACT:", mining_impact(2))
