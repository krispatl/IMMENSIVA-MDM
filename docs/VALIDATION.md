# Delivery checks — 13 October 2026

Version 1.1.0, based on STYLY-MDM 0.6.0. JERU networking remains on STYLY-NetSync 0.17.5.

- Three automated integration tests passed: branded routes/assets/admin handshake; two simulated devices and group-scoped launch, with the other device excluded; APK upload/download byte integrity.
- JavaScript syntax check passed. Chrome visual review confirmed all three official logos, connected server, empty real fleet, operator guide and the Lord Lyrical package shortcut.
- Windows portable runtime includes Python and dependencies. No Unity installation or Unity project is needed for MDM. Runtime and venue data are excluded from Git.
- Portable server start/health/stop passed on isolated ports 17080/17081 using only the bundled runtime.
- Branded server launched on port 7070, retaining the original JERU MDM data directory after an offline backup. The JERU launcher bridge and local portable source now start the branded adapter; game scenes and cue code were not modified.
- Physical headset deployment and multi-headset fleet commands have not been validated in this branding pass. Existing PICO client provisioning is retained; network reachability and permissions still require a venue test.
- No change to JERU choreography, stage alignment, song timing or Chroma source.

The console intentionally keeps STYLY's confirmations for destructive operations. No firewall rules or LBE maps are installed by the portable package.

## Operator UX pass

- Daily tasks separated into Open app, Install app and Send files. Maintenance is a separate menu, not an authentication or permissions system.
- Chrome checks against an isolated server with two online simulated headsets and one offline device: selection count, low-battery alert, command review, cancel, confirmed single launch, offline-only launch disabled, task switching and preserved destructive confirmations passed.
- The simulated transport received exactly one EXECUTE_LAUNCH after confirmation; cancellation produced no launch. No real headset commands were sent in these checks.
- Responsive view checked at 390 pixels, with no horizontal document overflow. Headset rows stack on narrow screens.
- Quick start included in the repository and in-app guide, with print styling. Official branding and funding footer retained.
