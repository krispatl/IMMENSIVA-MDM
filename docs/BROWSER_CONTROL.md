# Browser controls on PICO headsets

In the MDM console, select **one or more online headsets**, choose **Open URL**,
enter a complete `https://` or `http://` address, and press **Open URL on N headsets**
(**Open URL on headset** for a single selection). Offline headsets are skipped.
The console shows progress and a separate result for each headset; one failure
does not stop the others. The target list and URL are fixed when you submit, so
changing the selection during a batch does not send the URL to additional headsets.
In Live Ops, the form under **Headset controls → Open a website** controls the
single headset selected in its details panel.
Opening the browser can interrupt the current experience.

The address opens in the headset's browser, not on the operator PC. Query strings
and fragments are preserved. Venue LAN addresses such as
`http://192.168.1.20:8811/` are supported when reachable from the headset;
`localhost` would refer to the headset itself. A successful result confirms that
Android accepted the browser launch, not that the page finished loading.

## Requirements

- The existing STYLY-MDM client stays installed; no new client or helper APK is
  needed for these browser controls.
- Wireless ADB must already be enabled and authorized on each selected headset.
- The PC needs `monitor-tools/scrcpy-win64-v5.0.1/adb.exe` and its accompanying
  DLLs. The existing Monitor and Venue Suite packages include these tools.
- A browser must be installed, enabled and permitted by headset policy. If
  Android presents a browser chooser, set the default browser in the headset.

## Close all browser tabs

In MDM, select the headsets, choose **Open URL**, then click **Close all browser
tabs**. A URL is not required. Offline devices are skipped; progress and results
are shown for each online headset. Unsaved page input may be lost. Bookmarks,
cookies, saved logins, history, and downloaded files are not cleared.

The browser may briefly open to restore and close saved tabs. The command uses
the PICO browser's WebLayer tab interface over the existing authorized ADB
connection; it needs no additional headset APK. An unsupported browser reports
an error without resetting its data. This control is in the MDM console.

If PICO keeps its current system activity and refuses to launch the browser,
MDM reports that separately. Wake the headset and open its browser once, then
retry. Android can report `Status: ok` even when it did not start the browser;
MDM does not treat that response alone as success.

Each request verifies the headset serial and resolves the default browser, then
uses only the debugging socket matching that browser's process. A temporary
local ADB forward is removed afterward, including on failure or cancellation.
The command closes a snapshot of the page tabs and verifies that they disappeared.
It leaves workers alone and does not chase new pages opened during the operation.
A newly created empty tab may remain if the browser requires one; this is reported
explicitly. Any other remaining tabs produce a partial-failure result.
Tab addresses and titles are not returned to the console or stored in logs.

Reference: [Chromium tab-control endpoints](https://chromedevtools.github.io/devtools-protocol/).

## Packaging

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

The console sends up to four requests concurrently and skips headsets that were
offline when submitted. Each request still checks the headset's current status
and identity; a headset that disconnects before its request is reported as a
failure. Concurrent requests to the same browser control are rejected.
Failures are not automatically retried. The paired touch listener
retains its existing action allowlist and does not expose browser control.
The positioning and live-view holds are unchanged.

Reference: [Android intents and web URLs](https://developer.android.com/guide/components/intents-common#Browser)
and [browser selector category](https://developer.android.com/reference/android/content/Intent#CATEGORY_APP_BROWSER).

## Validation

Automated tests cover URL validation, unchanged query strings and fragments,
shell quoting, browser discovery, serial mismatch, offline and missing-tool
handling, launch errors and timeouts, API validation, cross-origin rejection,
and touch-listener limits.

UI regression tests also cover multiple selected headsets, offline and unselected
devices, partial failures, progress/results, bounded concurrency, duplicate
submission, and selection or URL changes during an active batch.

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

On 20 November 2026, closing tabs was verified on ESPRONCEDA-10 with PICO
browser 4.0.40: a single-tab probe reduced seven page tabs to six, then the full
command closed the remaining six and confirmed zero page tabs. Temporary ADB
forwards were removed after both checks. No browser data reset was used.
All 108 Python tests (plus four subtests) and 20 UI tests passed. New checks cover
tab-list verification, partial failures, replacement tabs, unrelated processes,
HTTP errors, cleanup on cancellation, API validation, and multiple selected HMDs.

The updated running MDM was then tested through its web interface with
ESPRONCEDA-01, ESPRONCEDA-02 and ESPRONCEDA-10 selected and no URL entered.
It reported two confirmed, zero failed and one offline skipped: headset 02 closed
all five page tabs, headset 10 confirmed no open tabs, and offline headset 01
received no request. An earlier batch also verified independent failure handling
when headset 04 retained its current system activity and refused to start its
browser. The resulting message now describes the blocked launch and suggests
opening the browser in the headset before retrying.
