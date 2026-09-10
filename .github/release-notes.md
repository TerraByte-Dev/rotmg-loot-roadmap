### Install — Windows 10/11, 64-bit

Download **{{SETUP}}** and run it. It installs to your user folder, so there is no UAC prompt.

**This build is not code-signed.** The first time you run it, Windows shows
**"Windows protected your PC"** — click **More info** then **Run anyway**. That is expected,
and it happens exactly once: in-app updates after this never show it again.

| File | SHA-256 |
| --- | --- |
| `{{SETUP}}` | `{{HSETUP}}` |
| `{{ZIP}}` | `{{HZIP}}` |

Check a download first with `Get-FileHash ".\{{SETUP}}" -Algorithm SHA256`.

### Portable ZIP

Run `Unblock-File ".\{{ZIP}}"` **before** extracting, or Windows copies the download mark onto
the .exe inside and you get the same prompt anyway. The portable build does not self-update.

### No install at all

`roadmap.html` is the whole thing in one file — open it in any browser, or drop it in a DM.
