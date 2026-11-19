# Open a URL on a PICO headset

In the MDM console, select **one online headset**, choose **Open URL**, enter a
complete `https://` or `http://` address, and press **Open URL on headset**.
In Live Ops, the same form is under **Headset controls → Open a website**.
Opening the browser can interrupt the current experience.

The address opens in the headset's browser, not on the operator PC. Query strings
and fragments are preserved. Venue LAN addresses such as
`http://192.168.1.20:8811/` are supported when reachable from the headset;
`localhost` would refer to the headset itself. A successful result confirms that
Android accepted the browser launch, not that the page finished loading.

## Requirements

- The existing STYLY-MDM client stays installed; no new client or helper APK is
  needed for URL navigation.
- Wireless ADB must already be enabled and authorized on the selected headset.
- The PC needs `monitor-tools/scrcpy-win64-v5.0.1/adb.exe` and its accompanying
  DLLs. The existing Monitor and Venue Suite packages include these tools.
- A browser must be installed, enabled and permitted by headset policy. If
  Android presents a browser chooser, set the default browser in the headset.

For the standalone MDM package, bundle the approved tools directory with:

```powershell
python scripts/build_windows.py --runtime "C:\path\to\runtime" --headset-tools "C:\path\to\monitor-tools"
```

The older `--recording-tools` switch remains an alias. A recording helper APK,
when present, is also bundled, but is not required for browser controls.
Update and restart the running server/package before using the new controls.

## Command handling

The server verifies the selected headset's ADB serial, resolves its
`MAIN` / `APP_BROWSER` handler without a URL, then sends an Android `ACTION_VIEW`
intent restricted to that browser's package. This lets Android select the
browser's URL handler instead of its launcher activity, and prevents another
app from claiming the URL's domain. Combining the URL with `--selector` failed
to resolve an activity on the connected PICO 4 Ultra Enterprise.
The Android shell command quotes
each argument, so query characters and shell metacharacters remain URL data.
Only HTTP and HTTPS URLs are accepted; embedded login credentials, other URI
schemes, spaces, control characters, and URLs longer than 4096 characters are
rejected before connecting to the headset. URLs are not stored in the activity
log; Android diagnostics that can echo URLs are not returned to operators.

Offline devices and concurrent requests to the same browser control are
rejected. Failures are not automatically retried. The paired touch listener
retains its existing action allowlist and does not expose browser control.
The positioning and live-view holds are unchanged.

Reference: [Android intents and web URLs](https://developer.android.com/guide/components/intents-common#Browser)
and [browser selector category](https://developer.android.com/reference/android/content/Intent#CATEGORY_APP_BROWSER).

## Validation

Automated tests cover URL validation, unchanged query strings and fragments,
shell quoting, browser discovery, serial mismatch, offline and missing-tool
handling, launch errors and timeouts, API validation, cross-origin rejection,
and touch-listener limits.

On 19 November 2026, all 56 Python tests passed, both web scripts passed syntax
checks, and MDM / Live Ops browser checks passed with a simulated ADB transport.
Those checks included success feedback, a browser launch failure, and recovery
with a venue LAN URL whose query parameters and fragment were preserved.
No physical headset commands were sent during these checks.

After the reported browser failure, read-only checks on the connected PICO
confirmed the old combined selector returned `No activity found`. Resolving the
browser separately returned `com.pico.browser.overseas`; a package-restricted
`ACTION_VIEW` resolved to `com.google.android.apps.chrome.IntentDispatcher`.
All 67 Python tests passed after this correction, including discovery failures
that must not launch anything. Live launch verification was blocked by automatic
approval review; first-run prompts and actual page loading still need checking
inside the headset.
