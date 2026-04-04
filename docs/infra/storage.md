# Storage

## Longhorn

- Storage node: rpi5-1 NVMe 2TB
- `defaultReplicaCount: 1` — single replica per volume
- rpi4-0, rpi5-0, murderbot: `allowScheduling: false` (pending RAID 5 setup)

## Planned: murderbot RAID 5

- 4x 8TB drives → mdadm RAID 5 (~24TB usable)
- Mount at `/var/lib/longhorn-murderbot`
- After setup: add as Longhorn storage node, bump replicas to 2
