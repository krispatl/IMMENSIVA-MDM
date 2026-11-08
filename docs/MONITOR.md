# IMMENSIVA operator monitor preview

## Temporary monitoring hold

Room positioning (**Start locating**) and screen streaming (**Live view**) are
temporarily disabled while the PICO storage issue is investigated. The dashboard
disables their buttons and room-outline measurement. The `track` and `view` API
actions return HTTP 403 before connecting over ADB, installing the probe APK,
starting its service, or launching scrcpy. Stop feed remains available.

Before deploying this change, stop active position feeds and close scrcpy windows
in the old instance. Stop Monitor or Venue Suite, replace it with the updated
sources or a newly built portable package, and restart. A Git update alone does
not stop an already running instance. A disconnected probe service expires after
its existing 30-minute limit. This change does not uninstall existing APKs or
delete headset files. Blackout/Restore still use the scrcpy display-power helper.

The hold is defined by `DISABLED_ACTIONS` in `immensiva_mdm/monitor.py`; there is no
operator toggle. Re-enable through a reviewed code change after investigation,
including restoring the dashboard guidance. The implementation below is retained
for that future change.

## Starting the monitor

Run Start Monitor.cmd and open http://127.0.0.1:7080 on the venue PC.
Keep the existing MDM server running on port 7070. The monitor reads its admin
feed and runs its own local web server, session store and position collectors.
Run Stop Monitor.cmd to stop the monitor. To stop individual position services,
select the headset and click Stop feed. Services also expire after 30 minutes.

## Operation

Open heads-up opens a read-only fleet window with large battery indicators,
foreground app names, connection and blackout status, and session timers.
Use Full screen for a dedicated operator display. Foreground app checks run
while this window is open and require authorized ADB access.

Select a headset. Choose its experience and enter the duration supplied by the
experience team. Start the operator timer when participation begins. Pause,
resume, finish and reset apply to that timer. The monitor does not infer the
experience's playback state. Timers are stored in monitor-data/sessions.json.

When enabled, Live view opens a separate scrcpy viewing window on the PC. The
viewer has control and audio disabled. Opening another headset replaces the current viewer.
Close that window to stop casting. Wireless ADB must be enabled and authorized.

When enabled, Start locating installs org.immensiva.monitorprobe, a separate Android
foreground service. It binds to the installed PICO Enterprise service, reads
HMD_POSITION_AND_ORIENTATION and LARGESPACE_MAP_INFO, and reports through ADB
logcat at two samples per second. Unity experience packages are not modified.
The service has a persistent notification and expires after 30 minutes.
It can be removed through Android app management or adb uninstall.

The plot uses global X/Z coordinates in metres and groups devices by the LBE
map fingerprint. It reads the irregular LBE play boundary from PICO's
get_large_space_bounds_info API and saves it with the map fingerprint.
This boundary is a play-area outline. Room dimensions and area are approximate.
Samples older than four seconds are marked stale. The room stays framed on the
outline as headsets move. Fit room includes the current marker positions.
When positioning is enabled, start locating one headset and select it, then
choose Measure outline. Capture at least three corners in perimeter order with
the same headset and save. The monitor stores the measured outline for that
LBE map. Use PICO boundary restores the headset-reported outline.
Freshness does not establish SLAM validity. Physical alignment, tracking loss,
recentring and map transitions require venue validation before operational use.

Blackout and Restore display control the physical panel through the pinned
scrcpy display-power API. Each command checks the physical SurfaceFlinger power
state. Audio can continue during blackout. These controls do not send sleep,
pause or app-launch commands. Physical power-button or OS events may override
the display state, which is refreshed periodically. A screen blackout does not
certify that an experience's playback continues on every app and firmware.
The UI shows an unconfirmed state when a fresh check cannot be obtained.
Display records survive monitor restart. Restore remains available for known
devices even if the MDM feed is unavailable, provided authorized ADB is reachable.

Blackout all applies to the current connected fleet. Restore all also retries
previously controlled devices. Group results distinguish successes, failures
and offline headsets that were skipped. These are individual network commands,
so fleet blackout is not frame-synchronised.

Stop experience detects running processes whose package IDs appear in the six
registered experience packages. It force-stops those packages and verifies that
their processes have ended. It finishes a matching operator timer. The UI asks
for confirmation before ending an experience, for one headset or the fleet.

In desktop Live Ops, use Fleet controls → Home menu → Enable for debugging and
Disable to lock single-press Home again. Enable restores the policy saved by the
rollout helper. Offline headsets are skipped; rerun the command after they connect.
The panel reports the last command's results, and Activity lists each headset's
result. It does not continuously read the fleet's Home menu policy.

## Compatibility observations

On 6 November 2026 the existing MDM feed reported 20 known headsets, 16 online.
All 16 reachable devices identified themselves over ADB as PICO 4 Ultra
Enterprise running Android 14. Two used PUI 5.15.5 and fourteen used PUI 5.15.7. Each had PICO casting
and ToB Enterprise services installed. The MDM client version 0.6.0 is separate
from the headset firmware version.

A separate probe on a PUI 5.15.5 headset read changing local and global
head poses and the active LBE map fingerprint while Modern Fossils remained
the foreground Unity activity. A scrcpy capture on that headset produced a
video recording with 76 decoded H.264 frames at 1024 by 512 pixels.
Casting also produced a recording on PUI 5.15.7.
The final collector also received global poses from
a PUI 5.15.7 headset while Modern Fossils was the foreground app. Both
headsets reported the same LBE map fingerprint.
An irregular 49-point boundary was read from the PUI 5.15.7 headset,
with approximate extents of 15.7 by 14.8 metres. The PUI 5.15.5 headset
returned boundary result code -1.
A short blackout
test on that headset changed the physical display from On to Off and back to On,
while Modern Fossils remained the foreground activity. Force-stop and group
failure handling are covered by command simulations rather than stopping a
live participant's experience during development. Eight monitor regression
checks cover packet reassembly for large outlines, physical versus virtual
display state, failed confirmation, partial fleet failure, restoration with an
unavailable MDM feed, the experience package allowlist and partial-stop timer
consistency. Browser checks cover marker selection, per-headset and fleet stop
confirmation targets, search and a narrow layout without horizontal overflow.
These checks do not validate every experience, every headset,
physical room alignment, or sustained multi-headset Wi-Fi performance.

The saved inventory in monitor-data/inventory.json is a dated snapshot.
Disconnected or newly added headsets may have unknown firmware.

## Rebuilding

Run monitor-tools/build-probe.ps1 with -AndroidPlayer pointing to the Unity
AndroidPlayer directory containing OpenJDK and SDK. This uses Android SDK
build-tools 36.0.0 and android-34. The Java service loads PICO's interface classes
from its installed system APK. This is device-specific and may need adaptation
after firmware changes. Retain the local signing key when updating an installed
probe. The generated diagnostic key uses the password android.

Obtain scrcpy 5.0.1 for Windows x64 from the official Genymobile release.
Place the extracted scrcpy-win64-v5.0.1 folder in monitor-tools.
The release archive SHA-256 is
b12a2c4ee8be317422451fc7dcf8ee20a71b5ea7ef9ad73ddd825a25316227a5.
The distribution includes its LICENSE.txt.

Package with scripts/build_monitor.py --runtime PATH --output NEW_FOLDER.
Pass --home-lock-apk PATH to include the same signed Home menu helper from the
venue monitor build and support disabling single-press Home.
Use a separate output folder. Existing outputs are rejected. Copy only the
approved portable runtime, never the original venue MDM folder or device data.

## References

- PICO Enterprise Android API documentation
  https://business.picoxr.com/us/doc/EnterpriseAPI-Intro
- scrcpy source and releases
  https://github.com/Genymobile/scrcpy
