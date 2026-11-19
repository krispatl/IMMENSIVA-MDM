# PICO native screen recording

Select one online PICO headset in MDM, choose **Screen recording**, then use
**Start recording** or **Stop recording**. The same controls appear under
**Headset controls** in Live Ops. Videos remain on the headset.

The console reads native recording state every five seconds while the controls
are visible. Start is enabled when stopped; Stop is enabled when recording.
Both are disabled when state is unavailable. The active flag includes the
startup countdown; it does not verify saved-video integrity or playback.

The helper rechecks state on the headset immediately before acting. Start while
already recording and Stop while already stopped do nothing. After a change,
the helper and PC check the resulting state before reporting success. Changes
made inside the headset appear on the next status refresh.

## Requirements and updates

- Authorized wireless ADB on the venue LAN (port 5555).
- `monitor-tools/scrcpy-win64-v5.0.1/adb.exe` and its accompanying DLLs.
- `monitor-tools/screen-recording.apk`, helper version 1.1 / versionCode 2.
- Firmware exposing the verified `pvr.screen.action` property: `record` means
  active; a present empty value means stopped. On PUI 5.15.7 with native recorder
  versionCode 100004072, the flag is absent until the first recording, which is
  handled as initial idle. An absent flag on other versions, or an unrecognized
  value, is unknown and never triggers a blind toggle.

The STYLY MDM client does not need replacing. The separate recording helper is
installed or updated on the first recording action after server restart. Status
checks only read state. Preserve `monitor-tools/recording.keystore` when rebuilding
so installed helpers can update.

Build with OpenJDK 17, Android SDK platform 34 and build-tools 36.0.0:

```powershell
./monitor-tools/build-recording.ps1 -AndroidPlayer "C:\path\to\AndroidPlayer"
```

Monitor and Venue Suite builds include the helper when present. For standalone MDM:

```powershell
python scripts/build_windows.py --runtime "C:\path\to\runtime" --recording-tools "C:\path\to\monitor-tools"
```

Update the server files and helper APK, restart MDM, and refresh the web page.
Old toggle-only requests are rejected with an instruction to reload.

## Implementation

The selected device's ADB serial is checked before reading state, installing the
helper, or issuing a command. The `org.immensiva.recording` service accepts only
`start` and `stop`. It reads native state locally and invokes the authorized
Enterprise `pbsRecord()` toggle once only when a change is needed. Persisted
receipts prevent the same request being repeated after helper process restart.
Commands are not automatically retried after a timeout or lost response.

The native ScreenCaptureService contains explicit start/stop commands and a
status query, but those interfaces require PICO's signature/privileged
`com.picovr.screencapture.permission.SHOT_AND_RECORD` permission. Standard ADB
was denied access on the tested headset. This implementation uses the existing
Enterprise API and native flag without changing permissions.

The flag is firmware-specific, not a documented Enterprise SDK status API.
Firmware updates need validation. Avoid simultaneous recording input from MDM
and headset controls: the vendor toggle and state read are separate operations.
The helper entry point remains protected by `android.permission.DUMP`.
The positioning/live-view holds and touch listener's allowlist remain in place.

## Validation

On 20 November 2026, PICO 4 Ultra Enterprise with PUI 5.15.7 and native recorder
1.0.4 (100004072) passed a physical pilot: Stop while stopped did nothing;
Start activated recording; repeating Start left it active; Stop cleared the
native flag. The headset was left stopped. A second headset with an initially
absent flag also reported stopped and accepted Stop without toggling.

The helper compiled and passed APK signature verification. All 89 Python tests
passed, covering unknown and initial state, action validation, device identity,
receipt correlation, no-op results, stale receipts, no automatic retries, API
validation, and touch-listener restrictions. Both web scripts passed syntax
checks. MDM and Live Ops Start/Stop controls passed simulated UI checks.
The deployed MDM web buttons also started and stopped recording on
ESPRONCEDA-10, with native-state confirmation shown in the console; the headset
was left stopped. Saved-video playback was not checked.

References: [PICO Enterprise API](https://business.picoxr.com/us/doc/EnterpriseAPI-Intro),
[official SDK recorder binding](https://github.com/Pico-Developer/PICO-Unity-Integration-SDK/blob/main/Enterprise/Scripts/Plugin/PXR_EnterprisePlugin.cs).
