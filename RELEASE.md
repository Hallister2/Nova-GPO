# Nova GPO Release Checklist

Use this checklist when publishing a new Nova GPO release.

## Build

1. Update and package the app:

   ```powershell
   .\PackageApplication.ps1 -Version 0.8
   ```

2. Confirm the script produced:

   ```text
   dist\Nova GPO.exe
   dist\installer\NovaGPOSetup_0.8.exe
   dist\installer\NovaGPOSetup_0.8.exe.sha256
   ```

3. Smoke test the packaged installer on a clean or secondary Windows profile.

## Publish

1. Create a GitHub release with a tag that includes the version, such as `v0.8`.
2. Upload both release assets:

   ```text
   NovaGPOSetup_0.8.exe
   NovaGPOSetup_0.8.exe.sha256
   ```

3. Keep the checksum file paired with the exact installer bytes. If the installer is rebuilt, regenerate and replace the checksum.
4. Add release notes that call out user-facing changes, parser changes, packaging changes, and known issues.

## Verify

1. In an older Nova GPO build, run **Check Updates** from the sidebar.
2. Confirm the update toast finds the new release.
3. Confirm the installer download reports checksum verification when a `.sha256` asset is present.
4. Confirm the installer launches only after verification succeeds.
