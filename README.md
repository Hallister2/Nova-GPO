<p align="center">
<img width="591" height="172" alt="Nova GPO - Application Logo" src="https://github.com/user-attachments/assets/12f9f171-96cd-42c7-bf58-e2a45c696157" />
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
- **GPO Viewer** - Open a backup and review metadata, configured policies, raw
  parsed settings, and source artifacts.
- **Compare Workspace** - Compare two backups with searchable, filterable
  findings for changed, missing, and added policy data.
- **Review Notes** - Track review status, priority, owner, ticket/change
  references, tags, notes, and supporting evidence for compare findings.
- **Saved Reports** - Save compare reviews to the local report archive so
  findings and notes remain available even if the source backup folders are
  later removed.
- **Global Search** - Search backup names, policy names, configured values, and
  parsed artifact content across available backup sources.
- **Exports** - Export compare results as HTML, Markdown, or JSON.
- **Update Checks** - Check GitHub releases for newer Nova GPO builds from the
  Settings page or automatically on startup.
- **Local-first Storage** - Settings, saved reports, and review data are stored
  locally under the user's application data folder.

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
%APPDATA%\Hallister Labs\Nova GPO
```

Useful subfolders include:

```text
%APPDATA%\Hallister Labs\Nova GPO\library\compares
%APPDATA%\Hallister Labs\Nova GPO\logs
```

Saved compare reports are independent archives. Removing a live backup source
does not automatically delete saved compare reviews.


## Status

Nova GPO is under active development. The current focus is improving parser
coverage, compare review workflows, report readability, and polished Nova Suite
desktop styling.
