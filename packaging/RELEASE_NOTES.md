## Download

| Your computer | File |
|---|---|
| Mac with Apple Silicon (M1/M2/M3/M4) | `Unwind-…-mac-arm64.dmg` |
| Mac with Intel | `Unwind-…-mac-x64.dmg` |
| Windows | `Unwind-…-Setup-x64.exe` (installer) or `Unwind-…-portable-x64.exe` (no install) |
| Ubuntu, Debian, Mint, Pop!_OS | `Unwind-…-linux-x64.deb` |
| Fedora, RHEL, openSUSE | `Unwind-…-linux-x64.rpm` |
| Any Linux | `Unwind-…-linux-x64.AppImage` or `Unwind-…-linux-x64.flatpak` |

**First launch.** These builds aren't code-signed yet, so your system will ask once:
- **macOS:** open the .dmg, drag Unwind to Applications, then right-click Unwind → **Open** → **Open**. On recent macOS: System Settings → Privacy & Security → **Open Anyway**.
- **Windows:** if SmartScreen appears, click **More info** → **Run anyway**.
- **AppImage:** `chmod +x Unwind-*.AppImage && ./Unwind-*.AppImage`
- **Flatpak:** `flatpak install --user Unwind-*.flatpak`, then `flatpak run io.github.jukeiss.Unwind`
- **.deb:** `sudo apt install ./Unwind-*.deb` · **.rpm:** `sudo dnf install ./Unwind-*.rpm`

Unwind opens in your browser at `http://127.0.0.1:7878` and shows a small window to reopen it or quit. Your notes are kept in `~/Unwind Vault`. Full binary analysis on macOS uses Apple's command-line tools (`xcode-select --install`).

Verify a download with `SHA256SUMS.txt`.
