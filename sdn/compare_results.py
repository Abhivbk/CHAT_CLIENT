#!/usr/bin/env python3
"""Compare Baseline vs SDN results. Usage: python3 compare_results.py
Reads results/results_baseline.csv and results/results_sdn.csv
(columns: test,n_clients,metric,value) and writes results/comparison.png + comparison.csv"""
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

D = "results"
frames = []
for label in ("baseline", "sdn"):
    f = os.path.join(D, "results_%s.csv" % label)
    if not os.path.exists(f):
        raise SystemExit("Missing %s - run that experiment first" % f)
    df = pd.read_csv(f)
    df["config"] = label
    frames.append(df)
df = pd.concat(frames)
summary = df.groupby(["test", "metric", "config"])["value"].agg(["mean", "std", "count"]).reset_index()
summary.to_csv(os.path.join(D, "comparison.csv"), index=False)
print(summary.to_string(index=False))

panels = [("rtt", "delivery_ms_avg", "RTT: avg delivery (ms)"),
          ("rtt", "delivery_ms_p95", "RTT: p95 delivery (ms)"),
          ("rtt", "lost", "RTT: messages lost"),
          ("scale", "delivery_ratio", "Scale: delivery ratio")]
fig, axes = plt.subplots(1, len(panels), figsize=(16, 4))
for ax, (t, m, title) in zip(axes, panels):
    sub = summary[(summary.test == t) & (summary.metric == m)].set_index("config")
    vals = [sub["mean"].get(c, 0) for c in ("baseline", "sdn")]
    errs = [sub["std"].fillna(0).get(c, 0) for c in ("baseline", "sdn")]
    ax.bar(["Baseline", "SDN"], vals, yerr=errs, color=["#888888", "#2a7de1"])
    ax.set_title(title, fontsize=10)
plt.suptitle("Chat performance under background congestion (mean +/- std over repeats)")
plt.tight_layout()
plt.savefig(os.path.join(D, "comparison.png"), dpi=150)
print("Saved results/comparison.png and results/comparison.csv")
