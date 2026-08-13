# Credential encryption key operations

Production must set `M3UGUIDE_CREDENTIAL_KEY` to a Fernet key through the
deployment secret manager. Generate it once with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Do not place the output in source control, application logs, container images,
database backups, or ordinary `.env` files. Back it up separately in the same
managed secret store used for other production recovery keys. A database backup
without this key cannot recover provider passwords; a leaked database alone is
not sufficient to decrypt them.

For a bare-metal installation started with `startup_app.sh`, an injected
`M3UGUIDE_CREDENTIAL_KEY` takes precedence. If it is absent, the script creates
`.secrets/m3uguide_credential.key` once with mode `0600` and exports its value
to the application process. The directory is ignored by Git. Persist and back
up this file; do not recreate it when upgrading or restoring the database. Set
`M3UGUIDE_CREDENTIAL_KEY_FILE` to use a protected path outside the checkout.

On first startup after deployment, legacy plaintext playlist passwords are
encrypted and removed from the JSON column. If the key is missing or invalid,
startup fails before migration rather than retaining plaintext.

## Rotation

1. Stop all m3u.guide application workers and take a database backup.
2. Export only the playlist `details` objects to a protected JSON array.
3. Store the old and new Fernet keys in separate protected files.
4. Run `rotate_credential_key.py input.json output.json --old-key-file OLD
   --new-key-file NEW` on an offline administrative host.
5. Import the new encrypted values transactionally, update the deployment
   secret, and start one worker for validation.
6. Verify provider health, then start the remaining workers.
7. Securely remove the plaintext-free intermediate files and retire the old key
   only after the backup retention window.

Never rotate by decrypting values into logs, shell arguments, or spreadsheet
exports. Rotate development provider, stream, and integration credentials before
any public deployment.
