---
name: machine-limits
description: "Dev-box safety limits — machine-specific (RTX 2080 Ti, 150W), NOT project constraints"
metadata:
  node_type: memory
  type: feedback
---

> **These are constraints of the specific development machine, not of FHRPY.**
> They do not apply to the toolbox itself or to other deployments.

On the original dev box: do **little compute** locally. The GPU is an **RTX
2080 Ti**, capped at **150 W** to avoid overheating (watch fan/temperature) —
this wattage figure is specific to that card. **No single foreground computation
longer than 2–3 min.** Heavy / GPU / large-RAM work runs inside **docker-compose**
with resource limits to avoid OOM crashing the box (docker is optional for the
public toolbox). Longer jobs run in the background or on a larger server.

**Why:** the dev machine thermally throttles / can crash on OOM.

**How to apply:** keep local runs short; offload heavy jobs to docker or a bigger
machine. See [[fhrpy-project]].
