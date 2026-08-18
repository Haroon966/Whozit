# Litestream (optional)

Whozit v4 uses one SQLite file per deployment (`WHOZIT_SQLITE_PATH`, default `data/whozit.db`).

For production, replicate that file with [Litestream](https://litestream.io/) so a lost volume can be restored without re-photographing every student.

## Example

```yaml
# litestream.yml
dbs:
  - path: /data/whozit.db
    replicas:
      - url: s3://your-bucket/whozit-program-a
        access-key-id: ${AWS_ACCESS_KEY_ID}
        secret-access-key: ${AWS_SECRET_ACCESS_KEY}
```

Run Litestream beside the Whozit container, sharing the same `/data` volume.

## Crypto-shred

Enrolment crops are encrypted with `WHOZIT_CROP_KEY`. Destroying that key renders crops unreadable even if a backup exists — use that for program off-boarding alongside deleting the SQLite file.
