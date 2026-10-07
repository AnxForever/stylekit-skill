# Installed Skill updates

Read this for update controls, pinned installations, or migration from older releases. The normal invocation check is in `SKILL.md`.

The bundled updater checks the official `AnxForever/stylekit-skill` GitHub `main` archive at most once every 24 hours. It changes only files recorded by the verified release manifest. It does not update the target project, install packages, or configure MCP.

If a managed file was edited or removed, or an incoming file collides with an untracked local file, the whole update is skipped. A forced check bypasses only the time interval, never local protection. Do not reset, delete, or overwrite local edits to make the check succeed.

## Controls

Use the script inside the installed Skill directory:

```bash
python3 "<skill-root>/scripts/update-skill.py" --status
python3 "<skill-root>/scripts/update-skill.py" --disable
python3 "<skill-root>/scripts/update-skill.py" --enable
python3 "<skill-root>/scripts/update-skill.py" --force-check
```

`--disable` stops automatic and forced checks until re-enabled. For an installation explicitly pinned to a tag or commit, disable updates before the first check: the updater does not detect installer pins and otherwise follows `main`. Do not change a user's deliberate pin or disabled setting.

On `UPDATED`, reopen `SKILL.md` before continuing. `UP_TO_DATE`, `CHECK_DEFERRED`, `UNAVAILABLE`, `LOCAL_CHANGES_PROTECTED`, `DISABLED`, and `BUSY` continue with the installed version. An offline result does not block the user's task. Unexpected errors should be reported without attempting destructive repair. The updater has transaction recovery and rollback; its regression tests cover interrupted writes and preservation of later edits.

## Older installations

For older installations already sourced from this repository, use `npx skills@latest update stylekit --project` in the project, or `npx skills@latest update stylekit --global` for the global copy. Omitting the scope flag selects both scopes for that name. The CLI follows the installation's recorded source, so it does not migrate a copy from another repository; inspect that source before choosing a reinstall. See the [official update implementation](https://github.com/vercel-labs/skills/blob/main/src/update.ts).

That installer may replace the entire Skill directory; preserve customizations before migration. The bundled updater's local-change protection applies after migration, not to another installer's replacement behavior. Clients decide whether to follow startup instructions; this is not a client-enforced update guarantee.
