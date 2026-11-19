# IMMENSIVA Venue Suite

Double-click **Start Venue Suite.cmd** to start MDM, Live Ops, and the bundled
STYLY NetSync server, then open the operator dashboard. If a NetSync
service already owns the configured ports, the dashboard shows **Existing
server** and uses the running service. Use **Stop Venue Suite.cmd** to stop
services started by this copy of the Suite. Runtime data and logs are in
`suite-data`.

**Temporary monitoring hold:** Live view, Start locating, and room-outline
measurement are unavailable while the PICO storage issue is investigated.
The server also rejects direct requests to start screen streaming or positioning.
Stop active feeds and close scrcpy windows before replacing an existing copy;
restart with the updated sources or a rebuilt portable package to apply the hold.
See [monitor deployment details](MONITOR.md#temporary-monitoring-hold).

The optional **Start recording** or **Stop recording** control triggers the headset's own
recorder and saves videos there. It requires the separate recording helper;
see [native recording setup](SCREEN_RECORDING.md).

**Headset controls → Open a website** sends an HTTP/HTTPS address to the selected
headset's browser using the bundled ADB tools. No extra APK is required.
See [browser control](BROWSER_CONTROL.md).

In **Prepare**, use the **STYLY NetSync** card to check the server and to start
or stop the bundled copy. **Open show launcher** opens the separate JERU timing
console. A NetSync startup problem appears in the card, with details in
`suite-data/logs/netsync.log` when a process was started.

## Pilot

Use a spare PICO headset on the trusted venue LAN. In its MDM client, enter the
venue PC's LAN address and TCP port **17080**. To return it to the venue system,
enter its previous MDM address and port. Use **Allow Venue Suite on Wi-Fi.cmd**
as administrator if the Windows firewall blocks access. The rules are scoped to
the package runtime, private networks, and the local subnet. Keep the ports on
the venue LAN. The package uses a separate UDP discovery port, **17081**.

The bundled NetSync server is version **0.17.5**. Use the same version in the
Unity experience. It listens on TCP **5555**, **5556**, **5557**, **8800**, and
TCP/UDP **49999** for discovery. The included firewall script allows those
standard ports for this package on private networks. For an isolated test,
create `suite-data/netsync-ports.json` while the Suite is stopped and override
any of `control`, `pub`, `transform`, `rest-api`, and `server-discovery` with
distinct port numbers. Configure test clients and firewall rules for that
profile before testing from another device.

- **Prepare** selects a room or individual headsets. Save the selection as a
  room, or review the targets before opening an experience, installing an APK,
  or sending files. Activity separates download progress from the headset's
  installation result. For advanced actions and folder transfers, use the MDM
  console. Avoid running the same operation on the same headset in both views
  at once, since STYLY 0.6.0 reports results by headset and operation identity.
- **Operate** shows foreground app, confirmed display state, battery, and
  operator timer. Start the timer when the participant begins. Live view and
  room positioning are temporarily unavailable; saved room outlines are retained.
- **Technician** saves default durations, enables or disables single-press Home
  for the online pilot fleet, and opens
  the phone pairing page. Home results reflect firmware feedback. Test with
  a controller before relying on the policy during a session.

To pair phones and tablets, stop the suite and double-click **Configure Venue
Wi-Fi.cmd**. Enter the PC's private venue LAN IPv4 address, then start the suite.
In **Technician → Phone & tablet pairing**, scan the QR code from a phone on the
same network. Phones use TCP **17083**. Use **Disconnect this browser** to clear
pairing. The PC dashboard listens on `http://127.0.0.1:17082`.

## Optional setup import

From the extracted suite folder, while the suite is stopped, use either or both
of these switches before the first start. Select copies of the old files if you
want a fixed snapshot. The import writes only labels, room groups, and measured
outlines to the new suite data directory.

```powershell
.\runtime\python.exe -m immensiva_mdm.suite_launcher --import-mdm "C:\path\to\device_registry.json"
.\runtime\python.exe -m immensiva_mdm.suite_launcher --import-outlines "C:\path\to\sessions.json"
```

## Build from source

Use the approved portable Python 3.11 Windows x64 runtime and `monitor-tools`
directory from an existing IMMENSIVA operator monitor. The build adds the
hash-pinned NetSync wheels and their licenses. The portable output runs offline.
Use a new output directory and optionally pass `--netsync-wheelhouse` to use a
local cache instead of downloading wheels during the build. [STYLY NetSync server](https://pypi.org/project/styly-netsync-server/0.17.5/)

```powershell
python scripts/build_venue_suite.py --runtime "C:\path\to\runtime" --tools "C:\path\to\monitor-tools" --output "C:\path\to\IMMENSIVA-Venue-Suite" --zip
```
