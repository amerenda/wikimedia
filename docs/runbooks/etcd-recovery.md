# etcd Recovery

Recovery procedure for etcd failures on the k3s RPi cluster.

## Auto-Recovery (Normal Case)

The `k3s-etcd-recovery.service` systemd unit runs before k3s on each controller. It:

1. Removes stale etcd members
2. Removes orphaned learners
3. Allows k3s to rejoin the cluster cleanly

No manual intervention needed for single-node restarts.

## Manual Recovery

If auto-recovery fails or all 3 controllers need recovery:

```bash
# On the surviving controller (or the one to restore from)
sudo systemctl stop k3s
sudo etcdctl member list
sudo etcdctl member remove <stale-member-id>
sudo systemctl start k3s
```

## Full Power Loss Recovery

_TODO: document full multi-node recovery procedure once tested._

See [Ansible BWS Refactor plan](../../plans/ansible-bws-refactor.md) and the `k3s-recover.yml` playbook.

## Validate Recovery

Run `smoke-test.yml` Ansible playbook to verify cluster health:

```bash
ansible-playbook smoke-test.yml
```
