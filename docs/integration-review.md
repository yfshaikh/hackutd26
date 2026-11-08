# Integration review checklist (apply when merging the parallel lanes)

Security-review findings to fix during integration, NOT while the lanes are mid-flight.

## defender.py — terminating-pod helper trusts the pod's own grace period (MEDIUM)

Lane 08's `_is_terminating()` (~defender.py:1300) does:

```py
grace = getattr(getattr(obj, "spec", None), "termination_grace_period_seconds", None)
if grace is None: grace = 30
return now < ts + timedelta(seconds=grace + 30)
```

Two problems:
1. It **trusts the attacker-controlled spec**: a pod with `terminationGracePeriodSeconds: 3600` sits Terminating for
   an hour and detection skips it that whole time — the exact fail-open the fix was meant to close.
2. `deletion_timestamp` (ts) **already includes the grace period**, so `grace + 30` double-counts.

Fix (cap, don't trust; ts is already the scheduled deletion time):
```py
MAX_GRACE = 30
# any terminating pod past its real deadline, or with an oversized grace, is still rogue
return now < ts + timedelta(seconds=MAX_GRACE)
```
Keep the finalizer check (a terminating pod WITH finalizers stays rogue). Re-run the lane-08 self-check after.

## cluster.py — pod annotations (DONE, committed 8257c21 working tree)

`_safe_annotations()` strips `kubectl.kubernetes.io/last-applied-configuration`. Verify it survived any lane merge.
