# `deploy/secrets/` — SOPS-encrypted secrets

This directory holds **encrypted** secret material for each deployment environment. The encryption is SOPS + age; see [ADR-0002](../../docs/adr/0002-secrets-management-sops-age.md) for the design and [`docs/runbooks/secrets.md`](../../docs/runbooks/secrets.md) for the operational procedures.

## Directory layout

```
deploy/secrets/
├── dev/                            # Anyone on the engineering team can decrypt
│   └── atms.env.sops               # Dev .env values (encrypted)
├── staging/                        # Ops + on-call only
│   └── atms.env.sops
└── prod/                           # Production ops + cluster-bound key only
    └── atms.env.sops
```

Files with the `.sops` segment are encrypted-at-rest by SOPS. They **are** safe to commit. Plaintext counterparts (`atms.env`) are produced by `make secrets-decrypt ENV=<env>` and are gitignored.

## Bootstrap (per developer)

1. **Install the tools**
   ```bash
   # macOS
   brew install sops age
   # Debian / Ubuntu
   apt install sops age
   ```
2. **Generate your personal age keypair**
   ```bash
   mkdir -p ~/.config/sops/age
   age-keygen -o ~/.config/sops/age/keys.txt
   chmod 600 ~/.config/sops/age/keys.txt
   ```
3. **Share your public key** (the line starting `# public key: age1...`) with the project owner. They add it to `.sops.yaml` under the appropriate recipient block and re-encrypts the affected files with `make secrets-rotate-recipients`.
4. **Pull the re-encrypted secrets and try decryption**
   ```bash
   git pull
   make secrets-decrypt ENV=dev
   # → produces .env at the repo root
   ```

## What goes in a secrets file

Plain `KEY=VALUE` lines (dotenv format) consumed by services via their Pydantic settings. Example shape:

```
# === Postgres ===
POSTGRES_HOST=postgres.dev.atms.svc.cluster.local
POSTGRES_PORT=5432
POSTGRES_DB=atms
POSTGRES_USER=atms
POSTGRES_PASSWORD=<encrypted-at-rest>

# === Auth (ADR-0006) ===
AUTH_HS256_SECRET=<encrypted-at-rest>
AUTH_ISSUER=https://idp.dev.atms.example/realms/atms
AUTH_AUDIENCE=atms-traffic-controller
```

The `.sops.yaml` `encrypted_regex` controls which keys SOPS encrypts inside a file — by default we encrypt anything matching `*PASSWORD*`, `*SECRET*`, `*TOKEN*`, `*KEY*`. Non-sensitive values (hostnames, ports) stay readable in the encrypted file for diff-friendliness.

## DO NOT

- **Do not** commit `~/.config/sops/age/keys.txt` (your private key).
- **Do not** commit decrypted `.env` files. They are in `.gitignore`; verify with `git status` before pushing.
- **Do not** put real production credentials in `dev/`.
- **Do not** rotate a recipient without re-encrypting; old material remains decryptable by anyone with the old key.
