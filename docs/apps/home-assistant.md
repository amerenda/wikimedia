# Home Assistant

Self-hosted home automation on Mac Mini M4. Configuration is fully managed as code in `mac-mini-compose`.

- **URL:** `ha.amer.dev`
- **Version:** 2026.3.4
- **Platform:** Docker Compose on Mac Mini (OrbStack), `host` network mode

## Why Mac Mini (Not k3s)

- **Host networking required** — mDNS/SSDP device discovery doesn't work through k8s NAT
- **Voice pipeline** — Whisper/Piper use Apple Silicon Metal GPU; in-cluster containers lose GPU access

## Integrations

| Integration | Details |
|---|---|
| Zigbee2MQTT | SMLIGHT SLZB-06MG24 coordinator at `10.100.20.179:6638` (Ember adapter, channel 15) |
| Philips Hue | Lights + dimmers via Z2M, scenes managed by Z2M Smart Lighting extension |
| Reolink cameras | Human/pet detection, privacy mode with verified LED control |
| UniFi | Device tracking for presence detection |
| Voice pipeline | Whisper (STT) + Piper (TTS) + OpenWakeWord |
| Tailscale | Remote access |
| PostgreSQL | History/statistics (unified Mac Mini Postgres) |
| GTFS Realtime | NYC subway departure times |

## Security System

Two Reolink cameras (bedroom + living room) with automated privacy control.

**Presence detection:** `group.members` (Alex + Eirill) via UniFi device trackers. Group is `home` if ANY member is home.

**Automations (3 total, YAML-only, git-managed):**

| Automation | Trigger | Action |
|---|---|---|
| Someone Home | `group.members` → `home` | Cameras off (privacy on) |
| Everyone Left | `group.members` → `not_home` for 5 min | Cameras on (privacy off) |
| Privacy Monitor | Every 1 minute | Drift correction — ensures LED/privacy state matches presence |

**Privacy mode sequence (hard requirement):**

- **Cameras off:** LED off → verify LED is off (retry loop, max 5 attempts) → privacy mode on
- **Cameras on:** Privacy mode off → wait → LED on → verify LED is on (retry loop)
- Same script used by automations AND dashboard buttons

**Camera entities per room:** privacy switch, status LED, person sensor, animal sensor, siren (disabled), camera stream.

## Smart Lighting

### Architecture

HA is the **source of truth** for schedules and scene values. A **Z2M extension** caches the config and handles all real-time execution independently of HA.

```
HA (source of truth)                    Z2M Extension (cache + executor)
┌─────────────────────┐                 ┌──────────────────────────────┐
│ Schedule profiles    │   MQTT push    │ Caches config to disk        │
│ Day assignments      │ ──────────────>│ Calculates current window    │
│ Scene values         │  zigbee2mqtt/  │ Stores scenes on Zigbee groups│
│ Per-room overrides   │  sl/config     │ Handles device announce      │
│ Dashboard UI         │   (retained)   │ Handles window transitions   │
└─────────────────────┘                 └──────────────────────────────┘
```

**HA is NOT in the critical path.** Switch press → Zigbee mesh → light on. No HA round-trip required.

### Schedule Profiles

Four named profiles with per-day assignment:

| Profile | Morning | Day | Evening | Night |
|---|---|---|---|---|
| Weekday | 06:00 | 09:00 | 17:00 | 22:00 |
| Friday | 06:00 | 09:00 | 17:00 | 23:00 |
| Saturday | 08:00 | 10:00 | 18:00 | 23:30 |
| Sunday | 08:30 | 10:00 | 17:00 | 22:00 |

Default assignments: Mon–Thu → weekday, Fri → friday, Sat → saturday, Sun → sunday. All editable on the Smart Lighting dashboard.

### Scene Values

Stored in `input_number` helpers (32 total: 5 rooms × 4 windows × brightness + color_temp for ambiance rooms). Editable via dashboard sliders.

### Z2M Extension (`smart-lighting.js`)

- Subscribes to `zigbee2mqtt/sl/config` for config from HA
- Caches to `data/external_extensions/sl-cache.json`
- Stores all 4 window scenes on every Z2M group via `scene_add`
- On window transition: updates `hue_power_on_*` firmware defaults on all bulbs, recalls scene on groups with lights on
- On `deviceAnnounce` (bulb power-on): pushes correct scene values
- Uses a separate MQTT client for commands (Z2M ignores its own messages)
- Publishes sync status to `zigbee2mqtt/sl/status` (retained)

### Zero-Flash Power-On

All Hue bulbs have `hue_power_on_brightness: 1` (LED physically dark at brightness 1). On wall switch power cycle, the bulb boots dark, Z2M extension detects `deviceAnnounce` and pushes the correct scene. First visible light is the correct scene.

Per-room `smart_power_on` toggle: when disabled, bulbs boot at actual scene values (instant, no Z2M delay). Auto-disabled when house mode is Guest.

### Zigbee Devices

**Lights (8 Philips Hue bulbs):**

| Device | Room | Type |
|---|---|---|
| living_room_1 | Living Room | White+Color Ambiance 800lm |
| bedroom_1, bedroom_2, lamp_1 | Bedroom | White+Color Ambiance 800lm |
| bathroom_1 | Bathroom | White+Color Ambiance 1100lm |
| hallway_1 | Hallway | White only |
| kitchen_1, kitchen_2 | Kitchen | White only |

**Switches (6 Hue Dimmer Switch gen 2):** one per room (hallway has 2). Currently bound to coordinator — pending rebind to Z2M groups for direct Zigbee control.

**Z2M Groups:** Living Room, Bedroom, Bathroom, Kitchen, Hallway — each with 4 stored scenes (morning/day/evening/night).

## NYC Subway Status

`shell_command.subway_status_update` fetches N/Q/4/5 train status from `api.subwaynow.app/routes`.

**Commute alert automation (pending deployment):** triggers on weekday mornings when phone disconnects from WiFi. Sends push notification with delay info.

## Dashboards

| Dashboard | Purpose |
|---|---|
| Dean | Main home dashboard (mushroom strategy), lighting controls, pet detection |
| Security | Camera privacy controls, feeds, detection events, guest list |
| Subway | Dynamic train times (shows home station or work station based on location) |
| Uni | Cat monitor (location, last seen, latest photo) |
| Smart Lighting | Schedule profiles, day assignments, room settings, scene editor, Z2M sync status |

## Configuration Layout

```
homeassistant/configuration/
├── configuration.yaml       # main config (template sensors, shell commands, MQTT sensors)
├── automations/             # YAML-only (3 security automations)
├── scripts/                 # camera privacy, SL config push, scene save, commute alert
├── helpers/generated/       # input_boolean, input_datetime, input_select, input_number, input_text, timer
├── blueprints/automation/   # room switch/timer/motion control (SL v2, pending cleanup)
├── dashboards/              # YAML dashboards (dean, security, subway, uni, smart_lighting)
├── groups.yaml              # members + guests presence groups
└── scenes.yaml              # HA scenes (20 total, 5 rooms × 4 windows)
```

**Important:** `automations.yaml` (UI-managed) MUST stay empty (`[]`). All automations are YAML-only in `automations/`. Duplicate automations caused by having both sources was a recurring issue — now resolved.

## Deployment

Managed by **Komodo** — polls `mac-mini-compose` repo, runs `docker compose up` on changes. Secrets injected from BWS via pre-deploy hook.

Config files are **read-only bind-mounted** into the container. The Z2M Smart Lighting extension is bind-mounted at `/app/data/external_extensions/smart-lighting.js`.
