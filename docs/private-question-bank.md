# Versioning a private question bank

Keep the public application checkout and private bank in separate Git histories. Hourglass reads installed questions from `tasks/`; a separate `private-question-bank/` repository can track snapshots of those questions, their assets, answer keys, summaries, roster and private author audit. Both locations are ignored by the public checkout. Never add a public remote to the private bank.

Initialize the private repository yourself, copy the intended bank and audit into it, inspect its staged contents, and commit. Include `question-summaries.json` with the snapshot. This is an explicit snapshot workflow: editing the private snapshot alone does not change installed questions.

To protect an external backup, create an ignored `private-data-paths.json` in the application root containing an object with a `paths` array of absolute backup directory paths. Both benchmark tool execution modes deny read and write access to those locations. Keep the registry outside version control because it contains your local paths. Never register a task workspace as private storage.

Run `python3 question_bank_backup.py --message "Describe the bank change"` from the application checkout. It refuses to overwrite uncommitted private-repository edits or use a repository with a remote. It snapshots installed tasks, summaries and effective order, commits changes, exports full Git history, restores the bundle into a temporary checkout, and compares all committed file contents. It then writes a uniquely named bundle and checksum manifest to the first registered backup directory. Use `--backup-dir` to select another registered directory. All earlier bundles are retained.

The output directory may be inside iCloud Drive. The working Git repository stays local; iCloud receives immutable completed bundles. Successful local write/readback does not establish cloud upload completion. Check sync status before relying on another device for disaster recovery.

Restore a chosen bundle into a new directory with `git clone /path/to/chosen.bundle restored-bank`. Inspect it before copying any questions into an application checkout. [Git’s bundle documentation](https://git-scm.com/docs/git-bundle) describes full-history backups and restoration.
