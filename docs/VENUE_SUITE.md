# IMMENSIVA Venue Suite

Double-click **Start Venue Suite.cmd** to open the operator dashboard. Use
**Stop Venue Suite.cmd** to stop both services. If either service cannot start,
the launcher reports its log path. Runtime data and logs are in `suite-data`.

## Pilot

Use a spare PICO headset on the trusted venue LAN. In its MDM client, enter the
venue PC's LAN address and TCP port **17080**. To return it to the venue system,
enter its previous MDM address and port. Use **Allow Venue Suite on Wi-Fi.cmd**
as administrator if the Windows firewall blocks access. The rules are scoped to
the package runtime, private networks, and the local subnet. Keep the ports on
the venue LAN. The package uses a separate UDP discovery port, **17081**.

- **Prepare** selects a room or individual headsets. Save the selection as a
  room, or review the targets before opening an experience, installing an APK,
  or sending files. Activity separates download progress from the headset's
  installation result. For advanced actions and folder transfers, use the MDM
  console. Avoid running the same operation on the same headset in both views
  at once, since STYLY 0.6.0 reports results by headset and operation identity.
- **Operate** shows foreground app, confirmed display state, battery, and
  operator timer. Start the timer when the participant begins. Casting opens a
  PC window. Position readings require authorized wireless ADB and a valid
  shared LBE map. Verify alignment in the room before relying on the plot.
- **Technician** saves default durations, measures the physical outline,
  enables or disables single-press Home for the online pilot fleet, and opens
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

Use the approved portable Python runtime and `monitor-tools` directory from an
existing IMMENSIVA operator monitor. The build copies only the signed headset
helpers and scrcpy from that directory. Its output contains the launchers, the
runtime, and the software. Use a new output directory.

```powershell
python scripts/build_venue_suite.py --runtime "C:\path\to\runtime" --tools "C:\path\to\monitor-tools" --output "C:\path\to\IMMENSIVA-Venue-Suite" --zip
```
