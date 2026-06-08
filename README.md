<p align="center">
<img width="591" height="172" alt="Nova GPO - Application Logo" src="https://github.com/user-attachments/assets/cfcab1d4-aef0-4251-8300-b867e53891e9" />
</p>

# Nova GPO

Nova GPO is a Hallister Labs / Nova Suite desktop application for reviewing,
searching, comparing, and archiving Group Policy backup evidence.

It is built for administrators who need a faster way to inspect exported GPO
backups, understand what changed between two backups, capture review notes, and
preserve compare results independently from the original backup folders.

## Highlights

- **Backup Library** - Scan one or more backup source directories and browse
  discovered GPO backups in a focused library view.
  <p align="center">
  <img width="1194" height="936" alt="image" src="https://github.com/user-attachments/assets/a9fa27d5-2801-4c35-b8f7-3f53fa7c8ce9" />
  </p>
- **GPO Viewer** - Open a backup and review metadata, configured policies, raw
  parsed settings, and source artifacts.
  <p align="center">
  <img width="1194" height="936" alt="image" src="https://github.com/user-attachments/assets/2e00171a-aa05-4ee6-9080-5a271c34339a" />
  </p>
- **Compare Workspace** - Compare two backups with searchable, filterable
  findings for changed, missing, and added policy data.
  <p align="center">
  <img width="1322" height="832" alt="image" src="https://github.com/user-attachments/assets/b81868d9-60a0-43f5-8490-eadf47799ffc" />
  </p>
- **Review Notes** - Track review status, priority, owner, ticket/change
  references, tags, notes, and supporting evidence for compare findings.
- **Saved Reports** - Save compare reviews to the local report archive so
  findings and notes remain available even if the source backup folders are
  later removed.
- **Global Search** - Search backup names, policy names, configured values, and
  parsed artifact content across available backup sources without blocking the
  main window during large searches.
- **Exports** - Export compare results as HTML, Markdown, or JSON.
- **Update Checks** - Check GitHub releases for newer Nova GPO builds from the
  sidebar or automatically on startup. Installer downloads support SHA-256
  release checksum verification when a checksum asset is published.
- **Local-first Storage** - Settings, saved reports, and review data are stored
  locally under the user's Documents folder.

## First Run

1. Launch Nova GPO.
2. Open **Settings**.
3. Add a backup directory that contains Group Policy backup folders.
4. Return to **Backup Library** and run **Scan**.
5. Select one backup to view it, or select two backups to compare them.

If the Backup Library is empty, the app shows setup guidance so you can add a
source directory or refresh the scan.

## Working With Backups

The Backup Library shows live backup sources discovered from configured
directories. These live backups are separate from saved compare reviews.

Use live backups to:

- Inspect a single GPO backup.
- Compare two backups.
- Search policy and artifact content.
- Confirm parser coverage and source files.

Use saved reports to:

- Preserve completed compare reviews.
- Reopen prior findings and review notes.
- Keep a durable archive that does not depend on the original backup directory.
- Rename or delete archived compare reviews when they are no longer needed.

## Parser Coverage

Nova GPO parses and normalizes common Group Policy backup content, including:

- `gpreport.xml` policy report data.
- Administrative Template policy settings.
- Registry policy values from `registry.pol`.
- Security template and policy text files.
- Group Policy Preferences XML artifacts.
- Backup metadata and manifests.
- Additional policy artifacts such as scripts, audit/security policy content,
  AppLocker-style data, and raw source files where supported.

Unsupported or partially supported files are still surfaced as artifacts when
possible so reviewers can find the original source material.

## Local Data

Nova GPO stores local application data in:

```text
%USERPROFILE%\Documents\Nova GPO
```

Useful subfolders include:

```text
%USERPROFILE%\Documents\Nova GPO\Config
%USERPROFILE%\Documents\Nova GPO\Library\Compares
%USERPROFILE%\Documents\Nova GPO\Logs
```

Saved compare reports are independent archives. Removing a live backup source
does not automatically delete saved compare reviews.

## Packaging Releases

Use `PackageApplication.ps1` from the repository root to build the PyInstaller
EXE, sync the Inno Setup version, build the installer, and generate the release
checksum.

```powershell
.\PackageApplication.ps1 -Version 0.8
```

The script produces:

```text
dist\Nova GPO.exe
dist\installer\NovaGPOSetup_0.8.exe
dist\installer\NovaGPOSetup_0.8.exe.sha256
```

Upload both `NovaGPOSetup_<version>.exe` and
`NovaGPOSetup_<version>.exe.sha256` to the GitHub release. Nova GPO uses the
checksum asset to verify downloaded installers before launching an update.

See [RELEASE.md](RELEASE.md) for the full release checklist.

## Status

Nova GPO is under active development. The current focus is improving parser
coverage, compare review workflows, report readability, and polished Nova Suite
desktop styling.
