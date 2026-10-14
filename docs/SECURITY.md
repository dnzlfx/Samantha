# Security notes

## Secrets policy

- Real credentials live only in a local `.env` file. That file is ignored by
  `.gitignore` and must never be committed.
- The repository ships `.env.example` with placeholder values. Copy it to
  `.env` and fill in your own values:

  ```bash
  cp .env.example .env
  # then edit .env and set OPENAI_API_KEY
  ```

- If `.env` was ever committed, assume the secret is compromised even after
  the file is removed from the latest commit: it stays in the git history.

## Rotating a leaked OpenAI key

If `OPENAI_API_KEY` was exposed (for example because `.env` was tracked):

1. Go to <https://platform.openai.com/api-keys>.
2. Revoke the exposed key immediately.
3. Create a new key and put it only in your local `.env`.
4. If the key had billing enabled, review usage for unexpected charges.

Removing the file from tracking does not delete history. To purge it from
history you would need a history rewrite (for example
[git-filter-repo](https://github.com/newren/git-filter-repo)); rotating the key
is the simpler and sufficient fix for a personal project.

## Reported issues

Please do not open a public issue for a security problem. Report it privately
to the repository owner instead.
