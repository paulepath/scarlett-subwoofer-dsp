# Focusrite Scarlett Subwoofer & Bass DSP Remote

A homemade CamillaDSP-based crossover for a Focusrite Scarlett 4i4, with a small web remote
for controlling it. Runs on a Raspberry Pi, public-facing copy at edifire.e-path.co.uk.

## Components

- `remote.py` — `aiohttp` server (port 5050) that talks to CamillaDSP over its websocket API
  (`ws://127.0.0.1:1234`). Switches between a flat/bypass config and a bass/subwoofer-filtered
  config, exposes live low-pass cutoff + gain adjustment, and toggles the Focusrite's hardware
  mono/stereo input mode via `amixer`.
- `index.html` — the web UI served at `/`.
- `gui-config.yml` — config for CamillaDSP's own bundled GUI (separate from the app above),
  defining a "Subwoofer Crossover" panel.
- `configs/` — the CamillaDSP configs: `default_config.yml` (loaded at boot),
  `subwoofer_active.yml` (bass mode), `flat_bypass.yml` (bypass mode).

Runs as two systemd user services: `camilladsp.service` and `camilla-remote.service`.

## Latency tuning

The app initially added ~100ms of round-trip delay. Root causes and fixes applied:

1. **`queuelimit` default (4) × `chunksize` (256)** — CamillaDSP's own docs formula
   (`2 × chunksize × queuelimit` samples of inter-thread queue) added up to ~43ms of
   buffering. Not needed here since capture and playback are the same synchronous PipeWire
   duplex device. Fixed by setting `queuelimit: 1` and `target_level: 256` explicitly in all
   three configs.
2. **Oversized ALSA hardware buffer on the Focusrite** — PipeWire had auto-negotiated
   `api.alsa.period-size=128`, `api.alsa.period-num=256` (~683ms buffer capacity). Fixed with
   a WirePlumber rule (system config, not in this repo — see below) shrinking it to
   `period-num: 3`.
3. **No real-time scheduling** — `rtkit-daemon` wasn't installed, so PipeWire/CamillaDSP
   threads ran `SCHED_OTHER`, competing with everything else on the Pi (Docker containers,
   CI runners, etc). Installed `rtkit`, enabled `rtkit-daemon.service`, and added the account
   to the `pipewire` group so its `RTPRIO`/`memlock` rlimits (set in
   `/etc/security/limits.d/25-pw-rlimits.conf`) actually apply. Requires a fresh login
   session (reboot) to take effect.

Reproducing steps 2-3 on another machine (not tracked in this repo since they're host-level,
not app-level):

```bash
sudo apt install rtkit
sudo systemctl enable --now rtkit-daemon
sudo usermod -aG pipewire <user>
# then reboot, or log out/in, for the group + rlimits to apply
```

```
# ~/.config/wireplumber/wireplumber.conf.d/50-focusrite-lowlatency.conf
monitor.alsa.rules = [
  {
    matches = [
      { node.name = "~alsa_input.usb-Focusrite_Scarlett_4i4.*" }
      { node.name = "~alsa_output.usb-Focusrite_Scarlett_4i4.*" }
    ]
    actions = {
      update-props = {
        api.alsa.period-size = 128
        api.alsa.period-num  = 3
      }
    }
  }
]
```

**Status:** steps 1 and 2 are verified working (no xruns, buffer confirmed shrunk via
`pw-dump`). Step 3's prerequisites (rtkit, rlimits) are in place, but PipeWire wasn't
observed claiming real-time priority after the reboot — worth revisiting, but not blocking
since it's a stability/headroom measure rather than the actual latency source.

Next lever, if further reduction is wanted later: dropping `chunksize` from 256 to 128 in all
three configs (roughly another ~5ms), at the cost of higher xrun risk on this shared box.
