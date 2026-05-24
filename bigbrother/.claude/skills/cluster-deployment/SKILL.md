---
name: cluster-deployment
description: When provisioning nodes, pushing binaries, or modifying deploy/ansible playbooks.
---

# Cluster deployment

## When this applies
- Editing anything under `deploy/`
- Bringing a new node online
- Pushing a new bigbrother binary to the cluster
- Modifying systemd units for `headd` / `clusterd`

## Core invariants
1. **Always `--check` (dry-run) first.** Every ansible-playbook invocation gets `--check --diff` before the real run. No exceptions on cluster-wide rollouts.
2. **One node at a time during binary push.** Use `--serial 1` until v1.0. Rolling failures across the whole fleet are not recoverable without on-site intervention.
3. **Previous systemd unit is the rollback.** Keep the prior `bigbrother-{headd,clusterd}.service` file with a `.prev` suffix on every push. `scripts/rollback-node.sh` swaps them back.
4. **The deployment image is the source of truth for system config.** Don't edit `/etc/` on running nodes by hand. If it's not in the image or in ansible, it doesn't exist.
5. **Nodes register with optibox before bigbrother starts.** Without the Pi knowing the node, we can't power-cycle it on failure — which is the only recovery path.

## Layout

```
deploy/
├── ansible/
│   ├── inventory.yml        # generated from STATE.md node table
│   ├── playbooks/
│   │   ├── provision.yml    # first-time setup
│   │   ├── push-binary.yml  # rolling binary update
│   │   ├── restart.yml      # systemctl restart on all
│   │   └── drain-node.yml   # graceful shutdown of one node
│   ├── roles/
│   │   ├── common/          # users, ssh keys, packages, NTP
│   │   ├── cuda/            # CUDA 12.6 toolkit + driver
│   │   ├── clusterd/        # systemd unit + binary
│   │   └── headd/           # only on head node
│   └── group_vars/
├── systemd/                 # canonical unit files
│   ├── bigbrother-clusterd.service
│   └── bigbrother-headd.service
└── pxe/                     # PXE boot config for unattended install
    └── preseed.cfg
```

## Push procedure (Phase 5+, not now)

```bash
# Dry run
ansible-playbook -i deploy/ansible/inventory.yml \
  deploy/ansible/playbooks/push-binary.yml \
  --check --diff --extra-vars "version=$(git rev-parse --short HEAD)"

# Real push, one at a time
ansible-playbook -i deploy/ansible/inventory.yml \
  deploy/ansible/playbooks/push-binary.yml \
  --serial 1 --extra-vars "version=$(git rev-parse --short HEAD)"

# Rollback (single node)
ssh nodeNN 'sudo /opt/bigbrother/scripts/rollback-node.sh'
```

## Network requirements (must hold on every node before deploy)
- Static IP per `docs/deployment/network-topology.md`
- MTU 9000 on the cluster interface
- NTP synced (chrony) to head node
- SSH key from headd authorized
- optibox Pi has the node registered (verify: `curl pi.local:8765/nodes`)
- `/opt/models/` exists and is owned by `bigbrother:bigbrother`

## systemd unit conventions
- `Restart=on-failure`
- `RestartSec=5s`
- `StartLimitBurst=3` — fail fast on persistent crashes; don't thrash
- Logs to journald; we scrape with `journalctl --output=json` if needed
- `User=bigbrother`, `Group=bigbrother` — never run as root

## Common mistakes
- Pushing a binary built against a different CUDA version than the deployment image (ADR-003: pin 12.6).
- Skipping `--check` because "it's a small change" — the small changes are exactly the ones with surprises.
- Forgetting to update `inventory.yml` when a node's IP changes — the playbook will silently skip the node.
- Editing `/etc/systemd/system/` directly instead of the role files — the next ansible run will revert your fix.
- Restarting `headd` without draining workers first — in-flight requests get lost.

## References
- @docs/deployment/node-bootstrap.md — bringing up a single node
- @docs/deployment/network-topology.md — IP plan, ports, MTU
- @docs/deployment/optibox-integration.md — Pi/MCP contract
- @STATE.md — current node roster
