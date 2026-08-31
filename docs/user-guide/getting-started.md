# Getting Started

## What is RomM-Dock?

RomM-Dock is a [Decky Loader](https://decky.xyz/) plugin that connects your self-hosted
[RomM](https://github.com/rommapp/romm) ROM library to Steam. Every game in your RomM library appears as a Non-Steam
shortcut in the Steam Library, complete with cover art, metadata, and collections. Games launch through
[RetroDECK](https://retrodeck.net/) or [EmuDeck](https://www.emudeck.com/), whichever you have installed.

## Prerequisites

Before installing the plugin, you need:

1. **A RomM server** — a running RomM instance with your ROM library. You'll need the server URL plus a username and
   password to connect the first time. The plugin exchanges those credentials for a RomM Client API Token and stores
   only the token — your password is never saved. Each user should have their own RomM account (see
   [Save Sync](save-sync.md) for why this matters).

2. **RetroDECK or EmuDeck** — installed on your Steam Deck or Linux PC. One of them handles the actual emulation. The
   plugin creates shortcuts that launch games through whichever backend you pick.

3. **Decky Loader** — the plugin framework. Install it from [decky.xyz](https://decky.xyz/) if you haven't already.
   Decky renders inside Steam's gamepad UI, and the plugin works wherever that UI runs: Gaming Mode on the Steam Deck,
   or Big Picture Mode on a Linux PC/HTPC — a dedicated Game Mode session is not required.

4. **A personal RomM account** — save sync ties saves to the authenticated user. Use your own account, not a shared one.

## Installation

**Not on the Decky store.** The store doesn't accept plugins whose code is written with AI assistance, and RomM-Dock's
is — see [How this is built](../index.md). Install it from the URL below.

### From Decky's "Install Plugin from URL"

1. Open the Quick Access Menu (QAM) in Gaming Mode by pressing the **...** button
2. Go to the Decky Loader tab (the plug icon) and open settings (gear icon)
3. Under **General → Other**, enable **Developer mode** — a new **Developer** tab appears in the sidebar
4. Open the **Developer** tab and select **Install Plugin from URL**
5. Enter the direct URL to the release zip

   The latest release always resolves through:

   ```text
   https://github.com/Crimson3076/romm-dock/releases/latest/download/romm-dock.zip
   ```

   Any other version is named the same way, by its tag:

   ```text
   https://github.com/Crimson3076/romm-dock/releases/download/romm-dock-v{VERSION}/romm-dock.zip
   ```

   Releases published before this project was named RomM-Dock use the older `tender-v{VERSION}/Tender.zip` form (and,
   before that, `decky-romm-sync-v{VERSION}/decky-romm-sync.zip`); their links keep working unchanged.

6. Decky downloads and installs the plugin automatically — no restart needed

**Tip:** You can also open the [releases page](https://github.com/Crimson3076/romm-dock/releases) in Steam's built-in
browser (Gaming Mode → long-press the Steam button → Web Browser), long-press the zip download link, and copy the URL
from there.

Any direct URL to the zip file works (GitHub releases, a self-hosted mirror, etc.) as long as it points to a valid
`.zip` containing the plugin.

### Updating from an older Decky-plugin install (RomM Sync / Tender)

Earlier releases installed under a different folder name — `decky-romm-sync`, then `romm-tender` — and Decky treats a
differently-named folder as a different plugin, so updating across either boundary can leave you with **two** entries:
the older one shown as **RomM Sync** or **Tender**, and the new one as **RomM-Dock**.

**Check one of your games before you remove the older plugin.** Every Steam shortcut the older plugin created starts
through a small file inside that plugin's own folder. RomM-Dock keeps its copy of that file under your home directory
instead — `~/.local/share/romm-dock/bin/rom-launcher` — and repoints your existing shortcuts at it the next time
RomM-Dock loads. Until that has happened, removing the older plugin stops all of your games from starting, and nothing
can put the file back.

The shortcut itself tells you which state you are in, and looking costs nothing:

1. Open any game RomM-Dock created in your Steam library and show its **Properties** — the gear icon on the game's page
   in Gaming Mode.
2. Read the **Target** path under **Shortcut**.

- **The path is inside `~/.local/share/romm-dock/bin/`** — your shortcuts no longer depend on the older plugin. Remove
  it wherever Decky lists your installed plugins, or keep it: it costs disk space and nothing else.
- **The path is still inside `homebrew/plugins/`** — leave the older plugin where it is. RomM-Dock repoints shortcuts
  when it loads, not when you open its panel, so reload RomM-Dock or restart Steam, then look again before you delete
  anything.

The new install also starts with its own settings and library: each install keeps its data in its own place, and nothing
copies the older one's settings or synced library across. Set RomM-Dock up as if it were new, and remove the older
plugin only once the check above passes.

### Manual installation (alternative)

1. Download `romm-dock.zip` from the [releases page](https://github.com/Crimson3076/romm-dock/releases)
2. Extract the zip to `~/homebrew/plugins/` on your device (via SSH, file manager, or USB)
3. Restart Decky Loader — either reboot, or run `sudo systemctl restart plugin_loader` via SSH
4. The plugin appears in your QAM under the Decky tab

## First-Time Setup

After installation, you need to connect the plugin to your RomM server:

1. Open the QAM and find **RomM-Dock**
2. Tap **Settings** in the menu, then **Connections** in the section list on the left
3. Enter your RomM server URL (e.g. `http://192.168.1.100:8080`) — this saves automatically
4. Tap **Sign in**, enter your RomM username and password once, and confirm
5. The **RomM Account** row shows **Signed in** on success. The plugin's main QAM panel has a **Connection** row that
   shows the live connection status whenever you open it — there is no separate test button

On a controller you can confirm a text field with the on-screen keyboard's **Enter** key (or the **R2** shortcut)
instead of navigating to the button — for example save-slot names and the artwork search. In the sign-in dialog, Enter
moves from the username to the password field and confirms only once every required field is filled; an incomplete form
can't be submitted, and **Cancel** leaves your existing sign-in untouched.

The plugin mints a RomM Client API Token from the credentials you enter and discards the password — it is never stored.
The same applies if the plugin auto-migrates an older install that still had a saved password: the password is discarded
as soon as a token is minted. If your RomM account is not allowed to create API tokens, the sign-in step reports that
and you'll need an account with token permissions.

<!-- Screenshot: Connection Settings page with URL field, Sign in button, and token status -->

Once connected, you're ready to sync your library. See [Configuration](configuration.md) for additional settings, or
jump straight to [Syncing Your Library](syncing-your-library.md).

---

**Next:** [Configuration](configuration.md)
