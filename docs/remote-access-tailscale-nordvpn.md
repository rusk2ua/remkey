# Remote access with Tailscale while NordVPN stays on

How to reach the shack PC from the road with **Tailscale**, while **NordVPN** keeps
running on the shack PC full time. It covers the shack PC (Windows 10), the Macs
and the iPad.

Short version:

- **AnyDesk** stays as the screen, keyboard and audio path. It already handles the
  shack PC's two displays and the 7610's USB audio, and nothing else here does that
  better.
- **Tailscale** carries remkey (TCP 7373) and gives you a private backup path to the
  shack PC. It replaces the router port-forward (section 5, Option A) and the
  AnyDesk TCP tunnel (Option B).
- **NordVPN** stays connected on the shack PC, with Tailscale excluded from it by
  split tunneling and a few settings changed (section 3).
- **On the Macs and the iPad, Tailscale and NordVPN can't run at the same time.**
  Disconnect NordVPN before you connect to the station (section 7).

---

## 1. How the pieces fit

```
 Mac (NordVPN OFF)                                   Shack PC (NordVPN ON)
 ┌──────────────────┐                                ┌──────────────────────────────┐
 │ remkey.client ───┼── Tailscale (WireGuard) ──────►│ tailscaled  ──► remkey.station│
 │                  │   100.x.y.z : TCP 7373         │  (split-tunneled: bypasses   │
 │                  │                                │   NordVPN)        port 7373  │
 │ AnyDesk ─────────┼── AnyDesk (as today) ─────────►│ AnyDesk: 2 displays + audio  │
 └──────────────────┘                                │                              │
                                                     │ browsers, updates, etc. ──►  │
                                                     │   NordVPN tunnel (unchanged) │
                                                     └──────────────────────────────┘
```

Why the split tunnel matters: Tailscale only routes traffic for its own
`100.64.0.0/10` addresses and leaves everything else to NordVPN, so the two don't
fight over routes. The trouble is NordVPN's firewall, which tends to drop traffic it
isn't carrying. Excluding Tailscale's programs from NordVPN lets Tailscale reach its
peers straight over the fiber, which also gets you direct (not relayed)
connections and the lowest latency.

A side effect worth knowing: with NordVPN on, the old router port-forward
(Option A) probably never worked reliably, because replies to inbound connections
leave through the NordVPN tunnel instead of the Spectrum line. Tailscale avoids
that problem entirely, since every connection is outbound from both ends.

---

## 2. Shack PC: install and set up Tailscale

Do this while you're at home, sitting at the shack PC.

1. Run the Tailscale installer you downloaded. Sign in with the same account you
   used to sign up.
2. In the Tailscale tray menu, open **Preferences** (newer builds call it
   **Settings**) and turn on **Run unattended**. Without this, Tailscale stops when
   you're logged out, and an unattended shack PC needs it running from boot.
3. Make sure **Use exit node** is **None**, and leave **Run exit node** off. An
   exit node can't coexist with NordVPN.
4. Open the admin console (<https://login.tailscale.com/admin/machines>) on any
   computer:
   - Rename the shack PC to something short, e.g. `shack` (**…** menu →
     **Edit machine name**).
   - **…** menu → **Disable key expiry**. Otherwise the shack PC drops off the
     tailnet after 180 days and you can't fix it from the road.
   - Note its `100.x.y.z` address. It doesn't change, so the clients use it
     directly.
5. In PowerShell (no admin needed):
   ```
   tailscale status
   tailscale ip -4
   ```
   `status` should list the shack PC and any other devices you've added.

Tailscale sets its adapter to the **Private** network category in Windows. If the
tray ever shows *"Failed to set the network category to private"*, restart
Tailscale and check that NordVPN's split tunneling (next section) is in place.

---

## 3. Shack PC: NordVPN settings

Open the NordVPN app → the **gear icon** (bottom left) → work down the list below.
Names move between app versions; if a setting isn't where this says, use the search
box at the top of NordVPN's settings.

| Setting | Where (Windows app) | Set to | Why |
|---|---|---|---|
| VPN protocol | Settings → Connection | **NordLynx** (already) | Leave as is. |
| Auto-connect | Settings → Connection (or General) | **On**, "Always" / "On all networks" | NordVPN comes back by itself after a reboot. |
| **Meshnet** | Varies by version | **Off** (check it with PowerShell; see below) | Meshnet uses the same `100.64.0.0/10` address block as Tailscale. Both on = address conflict. |
| **Kill Switch** | Settings → Kill Switch | **Internet Kill Switch: Off.** App Kill Switch: optional (browsers only) | If NordVPN ever drops with the Internet Kill Switch on, it blocks *all* traffic, Tailscale and AnyDesk included, and you're locked out until someone is at the PC. |
| **Split tunneling** | Settings → Split tunneling | **On**, mode **"Bypass VPN for selected apps"**, with the Tailscale programs below | Lets Tailscale reach its peers directly. |
| Threat Protection / custom DNS | Settings → Threat Protection, Settings → Connection | Either is fine | Can stop Tailscale names (MagicDNS) resolving *on the shack PC*. Nothing here relies on that: the clients use the 100.x address. |
| Stay invisible on LAN / Allow LAN discovery | Settings → Connection (or General) | Either is fine | Affects your home LAN, not the tailnet. |

### Checking and turning off Meshnet

NordVPN keeps moving Meshnet's controls between app versions (the 2026 redesign
shows only file-transfer options on the Meshnet screen), so check the network
adapter instead of the app. In PowerShell:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object IPAddress -like '100.*' |
  Format-Table InterfaceAlias, IPAddress
```

- **No rows** (before Tailscale is installed), or **one row on the Tailscale
  adapter**: Meshnet is off. Nothing to do.
- **A row on a NordLynx/NordVPN adapter**: Meshnet is active. Find its
  disable option in the app (older versions: the dropdown arrow next to the
  Meshnet toggle on **Devices in Meshnet** → **Disable for this device**; in
  newer versions try the search box in Settings), then run the check again.

### Adding Tailscale to split tunneling

1. Settings → **Split tunneling** → turn it **On** → mode **Bypass VPN for selected
   apps**.
2. Click **Add apps** → **Browse apps** and go to `C:\Program Files\Tailscale\`.
3. Add **`tailscaled.exe`** (the service that carries the packets).
4. Repeat and add **`tailscale-ipn.exe`** (the tray app). A user with this same
   combination reports that adding it fixed reaching their tailnet; adding both
   costs nothing.
5. Leave AnyDesk alone. It works today; don't change two things at once.
6. **Disconnect and reconnect NordVPN** so the rules take effect, then in
   PowerShell:
   ```
   tailscale netcheck
   tailscale status
   ```
   `netcheck` should show **UDP: true** and your Spectrum public IPv4, not a
   NordVPN server address. If it shows the NordVPN address, the split tunnel isn't
   applied; recheck the paths and reconnect again.

### Plan B if the shack PC still can't be reached over Tailscale

NordVPN's split tunneling has a second mode, **"Enable VPN for selected apps
only"**: only the apps you list (your browsers, for example) go through NordVPN,
and everything else (Tailscale, AnyDesk, N1MM+, Windows Update) uses the fiber
directly. It's the most robust arrangement for a station PC. Use it if section 9's
tests fail with the normal mode.

---

## 4. remkey over Tailscale

### Shack PC

1. In `station.toml`:
   ```toml
   listen_host = "0.0.0.0"
   listen_port = 7373
   ```
   `0.0.0.0` (not the 100.x address) means the service starts cleanly even if it
   comes up before Tailscale at boot. The firewall rule below is what restricts it.
2. PowerShell **as Administrator**, allow 7373 from the tailnet only:
   ```powershell
   New-NetFirewallRule -DisplayName "remkey station (Tailscale only)" `
     -Direction Inbound -Protocol TCP -LocalPort 7373 `
     -RemoteAddress 100.64.0.0/10,fd7a:115c:a1e0::/48 `
     -Action Allow -Profile Any
   ```
3. Remove the old, wider permission. Open `wf.msc` → **Inbound Rules**, sort by
   **Program**, and **disable** any *Allow* rules for `python.exe` / `py.exe` that
   Windows created when the station first ran (they allow every address).
   Disabling (not deleting) makes it easy to undo.
4. If you set up the **router port-forward** for 7373 (README Option A), **delete
   it** on the Spectrum router. Nothing needs it now.
5. Restart the station service (or the Task Scheduler task).

### Mac

In `client.toml`:
```toml
station_host = "100.x.y.z"   # the shack PC's Tailscale address from section 2
station_port = 7373
```
(The MagicDNS name, e.g. `shack`, also works when NordVPN is off on the Mac, but
the address has no DNS dependence at all.)

Bonus: the remkey link is now encrypted end to end by Tailscale (WireGuard), which
closes the "traffic isn't encrypted" note in `SECURITY.md`.

---

## 5. AnyDesk: keep it for screen and audio

AnyDesk stays the primary way to see and drive the shack PC:

- **Dual displays:** AnyDesk shows the shack PC's real displays as they are. Windows
  Remote Desktop (RDP) instead builds a new desktop sized to your Mac's screen, so
  N1MM+, GH Everyware and the 7610 display window get rearranged every time you
  connect.
- **Audio:** the 7610's USB audio → "Listen to this device" → AnyDesk audio path
  (README section 6, "Audio") is already set up. RDP is known to hide or upset radio
  audio devices; FlexRadio DAX and WSJT-X users report the radio's sound devices
  disappearing over RDP.

Nothing in AnyDesk has to change. Optional, once everything else works: in AnyDesk
on the shack PC, **Settings → Connection → Allow direct connections** (TCP 7070),
then from the Mac enter the shack PC's **Tailscale address** in AnyDesk's address
field instead of its AnyDesk ID. That sends the session privately over the tailnet
instead of via AnyDesk's relays. If AnyDesk won't connect that way, go back to the
ID; nothing else depends on it.

---

## 6. Backup path: Remote Desktop over Tailscale (emergency only)

If AnyDesk itself breaks while you're away (crashed, updated badly, account
problem), Tailscale still gives you a way in:

- **Needs Windows 10 Pro.** Check with **Settings → System → About → Edition**.
  Windows 10 Home can't accept Remote Desktop connections.
- On the shack PC: **Settings → System → Remote Desktop → On**, and add your Windows
  user if asked. Restrict it to the tailnet like remkey:
  ```powershell
  Get-NetFirewallRule -DisplayGroup "Remote Desktop" |
    Set-NetFirewallRule -RemoteAddress 100.64.0.0/10,fd7a:115c:a1e0::/48
  ```
- On the Mac or iPad: Microsoft's **Windows App** (formerly Remote Desktop) →
  add PC → the shack PC's 100.x address.
- Expect: the shack PC's local monitors lock, the window layout gets rearranged,
  and radio audio may not work. Use it to restart AnyDesk (or reboot), then go back
  to AnyDesk.

---

## 7. Macs (M4 Pro MBP, M3 Air)

1. Install Tailscale (Mac App Store or the standalone download from tailscale.com)
   and sign in with the same account.
2. **macOS can't run Tailscale and NordVPN together.** With NordVPN connected, new
   connections to tailnet addresses time out even though Tailscale says it's
   connected. Tailscale's maintainers treat this as a macOS limitation (one VPN at a
   time), not a bug that will be fixed.
3. So, to operate:
   1. **Disconnect NordVPN** (and turn off its auto-connect on the Macs, or it will
      reconnect on a new Wi-Fi network mid-session).
   2. Connect Tailscale.
   3. Start AnyDesk and `remkey.client`.
4. You give up nothing important on hotel or club Wi-Fi: the remkey link (Tailscale)
   and AnyDesk are both encrypted end to end. Only your *other* browsing loses
   NordVPN's cover while you operate.
5. If you want full-tunnel privacy *and* the tailnet at the same time, Tailscale's
   Mullvad exit-node add-on does that (paid, per 5 devices). It replaces NordVPN on
   the Mac rather than running alongside it. Not needed for station use.

## 8. iPad

iPadOS allows one VPN at a time, so it's Tailscale or NordVPN, never both. Since
you rarely run a VPN on the iPad, just install Tailscale and AnyDesk from the App
Store. remkey's client is Mac-only, so the iPad is for watching, tuning and
logging, not paddle CW.

---

## 9. Test before you leave home

Do these **at home**, with the Mac on the **phone hotspot** (not home Wi-Fi), so
you're testing the real path.

- [ ] Shack PC: NordVPN connected, `tailscale status` shows the Mac.
- [ ] Mac (NordVPN off): `tailscale ping 100.x.y.z` → replies, ideally ending
      `via <Spectrum IP>:<port>` (direct). `via DERP(...)` means relayed: works,
      but slower; recheck section 3.
- [ ] Mac: `nc -vz 100.x.y.z 7373` → `succeeded`.
- [ ] Mac: `remkey.client` connects; the station log shows the login. Key with
      `--dry-run` on the station first.
- [ ] AnyDesk session works as before, both displays and audio.
- [ ] **Reboot the shack PC remotely** (Start → Restart from AnyDesk) and confirm
      that, without touching it, NordVPN reconnects, Tailscale comes back, the
      remkey task starts after login, and AnyDesk reconnects.
- [ ] Disconnect NordVPN on the shack PC briefly: Tailscale and AnyDesk should keep
      working (this proves the kill switch is off).
- [ ] Optional: Remote Desktop to the 100.x address works (section 6).

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Mac: Tailscale "Connected", but nothing on the tailnet answers | NordVPN connected on the Mac | Disconnect NordVPN on the Mac (section 7). |
| `tailscale ping` works, `nc` to 7373 times out | Windows Firewall, or station service not running | Check the rule from section 4 exists and is enabled; check the station console/log. |
| `tailscale ping` goes via DERP every time | Shack PC's Tailscale traffic still inside NordVPN | Recheck split tunneling paths, reconnect NordVPN, run `tailscale netcheck`. |
| Shack PC drops off the tailnet entirely | Key expiry, or Tailscale not running unattended | Section 2 steps 2 and 4. |
| Shack PC unreachable by anything after a NordVPN hiccup | Internet Kill Switch on | Turn it off (section 3). |
| Tailscale shows a Meshnet/address warning, or tailnet traffic goes nowhere | NordVPN Meshnet turned on | Turn Meshnet off. |
| Still unreachable with everything above checked | NordVPN's firewall blocking the tailnet anyway | Plan B in section 3 ("Enable VPN for selected apps only"). |

## What not to do

- Don't make the shack PC a Tailscale **exit node** or **subnet router**; both need
  their own aggressive routing that collides with NordVPN.
- Don't turn on NordVPN **Meshnet** on any device that runs Tailscale.
- Don't change Tailscale's address range or switch it to userspace mode to "fix"
  NordVPN; neither addresses the actual problem (NordVPN's firewall).

## References

- Tailscale: [Can I use Tailscale alongside other VPNs?](https://tailscale.com/kb/1105/other-vpns)
- Tailscale: [Windows network category message](https://tailscale.com/docs/reference/messages/client/set-network-category-failed)
- Tailscale issue [#21248](https://github.com/tailscale/tailscale/issues/21248): macOS tailnet TCP fails while NordVPN is connected
- NordVPN: [Split tunneling](https://support.nordvpn.com/hc/en-us/articles/19618692366865-What-is-Split-Tunneling-and-how-to-use-it)
- Home Assistant community: [Tailscale + NordVPN on Windows via split tunneling](https://community.home-assistant.io/t/accessing-ha-on-win11-with-both-nordvpn-and-tailscale-active/1010677)
- AnyDesk: [Client settings (direct connections)](https://support.anydesk.com/docs/settings)
