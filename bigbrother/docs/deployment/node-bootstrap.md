# Node bootstrap

A runbook for bringing a single new node into the cluster. All steps below are **Phase 5+** unless noted. Until Phase 5, nodes are configured by hand against this document.

## 1. Hardware checklist

Before powering on:

- [ ] PSU sized for the GPU (P100 = 250W, GTX 1060 = 120W) plus 100W system overhead
- [ ] At least 32 GB RAM (16 GB minimum for M2 / CPU-only nodes)
- [ ] 1× SATA SSD ≥ 256 GB for OS and binaries
- [ ] 1× SATA SSD or NVMe ≥ 1 TB for model storage (under `/opt/models/`)
- [ ] Onboard 1 GbE (mandatory, cluster subnet)
- [ ] 10 GbE add-in NIC if this node is going on the P100↔P100 DAC link
- [ ] BMC / IPMI accessible (for optibox harness; even consumer boards need *some* remote power control — usually the optibox Pi via relay)
- [ ] Static MAC in BIOS, jot it down

## 2. OS install — Debian 12 minimal

Boot via the bigbrother PXE setup (see `deploy/pxe/preseed.cfg`, Phase 5) or USB stick.

Selections at the installer:

- Hostname: `node-NN` (NN = last octet of the static IP from `docs/deployment/network-topology.md`)
- Domain: leave blank
- User: `bigbrother`, password ignored (we use SSH keys)
- Software selection: "SSH server" only — no desktop, no web server, no print

After first boot:

```bash
ssh root@node-NN  # using temporary password set at install
```

## 3. Base package list

```bash
apt update && apt install -y \
  build-essential cmake git curl wget vim tmux \
  pkg-config libzmq3-dev libuv1-dev \
  chrony \
  ethtool iperf3 net-tools \
  prometheus-node-exporter \
  python3 python3-venv python3-pip
```

CUDA installs separately (see step 5).

## 4. Networking

```bash
# Static IP
cat > /etc/network/interfaces.d/cluster <<EOF
auto eth0
iface eth0 inet static
  address 192.168.1.NN/24
  gateway 192.168.1.1
  dns-nameservers 192.168.1.1
  mtu 9000
EOF

systemctl restart networking

# Verify jumbo
ping -M do -s 8972 192.168.1.10  # head node
```

If jumbo fails, drop to MTU 1500 cluster-wide and add an entry to `plan/BLOCKED.md`. Mixed-MTU is worse than uniform 1500.

10 GbE direct link (P100 boxes only): see `docs/deployment/network-topology.md`.

## 5. CUDA 12.6 (GPU nodes only)

Per ADR-003 we pin CUDA at 12.6. Newer breaks Pascal.

```bash
# Add NVIDIA repo
wget https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/cuda-keyring_1.1-1_all.deb
dpkg -i cuda-keyring_1.1-1_all.deb
apt update

# Install pinned toolkit + driver
apt install -y cuda-toolkit-12-6 cuda-drivers
nvidia-smi  # must show driver supporting CUDA 12.6, GPU present
```

After install, blacklist nouveau (still bites occasionally):

```bash
echo 'blacklist nouveau' > /etc/modprobe.d/blacklist-nouveau.conf
update-initramfs -u
reboot
```

## 6. SSH keys

Push the head node's bigbrother key into the new node's `~/.ssh/authorized_keys`:

```bash
# From head:
ssh-copy-id -i ~/.ssh/bigbrother_ed25519.pub bigbrother@node-NN
```

Verify password login is disabled (`/etc/ssh/sshd_config`: `PasswordAuthentication no`).

## 7. NTP

```bash
# Point chrony at head node
sed -i '/^pool/d' /etc/chrony/chrony.conf
echo 'server 192.168.1.10 iburst' >> /etc/chrony/chrony.conf
systemctl restart chrony
chronyc tracking  # check sync
```

Time drift across the cluster must be < 50 ms; heartbeat timing depends on it.

## 8. optibox registration

The optibox Pi controlling this node's PSU/BMC must know the node before bigbrother starts. From the Pi:

```bash
curl -X POST localhost:8765/register \
  -H 'content-type: application/json' \
  -d '{"node_id":"node-NN","ip":"192.168.1.NN","power_method":"relay","relay_gpio":17}'
```

Verify from head:

```bash
curl pi-NN.local:8765/nodes | jq '.[] | select(.node_id == "node-NN")'
```

## 9. Filesystem layout

```bash
mkdir -p /opt/bigbrother /opt/models /var/log/bigbrother
chown -R bigbrother:bigbrother /opt/bigbrother /opt/models /var/log/bigbrother
```

`/opt/bigbrother/` will hold the bigbrother binary (pushed by ansible). `/opt/models/` will hold GGUF files (synced by `scripts/sync-models.sh` or rsync from head, Phase 5).

## 10. Hand off to ansible

At this point the node is ready for the ansible-driven rollout. From head:

```bash
echo 'node-NN' >> deploy/ansible/inventory.yml  # actual edit, this is illustrative
ansible-playbook -i deploy/ansible/inventory.yml \
  deploy/ansible/playbooks/provision.yml \
  --limit node-NN --check --diff
# review output, then drop --check
```

After provision finishes, this node should appear in `STATE.md` and start sending heartbeats once `clusterd` is started.

## 11. Smoke test

```bash
# from head
ssh node-NN 'nvidia-smi'                     # GPU healthy (if applicable)
ssh node-NN 'systemctl status bigbrother-clusterd'  # active
curl -s node-NN:9090/metrics | grep bb_epoch       # metrics endpoint up
```

If all three pass, the node is officially online. Update `STATE.md` table.

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Jumbo ping fails | Switch port not configured for MTU 9000 | Reconfigure switch, or drop cluster MTU to 1500 |
| `nvidia-smi` says no devices | Nouveau still loaded | Verify blacklist took effect, rebuild initramfs |
| `chronyc tracking` shows large offset | Firewall blocking NTP | Allow UDP 123 from head |
| `clusterd` won't start | Wrong CUDA on binary | Rebuild with CUDA 12.6 toolchain |
| Heartbeats not seen by head | Cluster firewall blocking UDP 11002 | `ufw allow from 192.168.1.0/24 to any port 11002 proto udp` |
