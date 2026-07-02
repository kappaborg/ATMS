# Runbook: Secrets management (SOPS + age)

**Owning component:** `deploy/secrets/`, `.sops.yaml`, `Makefile` secrets targets, `.github/workflows/ci.yml` (`secrets-check` + `gitleaks`).
**Design:** [ADR-0002](../adr/0002-secrets-management-sops-age.md).
**Audience:** Every engineer on the project (for the bootstrap), ops (for cluster integration, key rotation).

This runbook tells you how to add a secret, decrypt for local dev, rotate a key, and handle a suspected leak. **Read it before touching anything under `deploy/secrets/`.**

---

## 1. One-time bootstrap (per developer)

```bash
# 1. Install the tools.
brew install sops age            # macOS
# apt install sops age            # Debian/Ubuntu
# choco install sops age          # Windows (or use WSL)

# 2. Generate your personal age keypair.
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
chmod 600 ~/.config/sops/age/keys.txt

# 3. Read the public key (the line starting with "# public key:").
grep -m1 'public key' ~/.config/sops/age/keys.txt

# 4. Share the public key (`age1...`) with the project owner. They
#    edit .sops.yaml under the appropriate recipient block and run
#    `make secrets-rotate-recipients`.

# 5. Pull and verify decryption.
git pull
make secrets-decrypt ENV=dev
cat .env                                  # confirm you can read it
```

**Never commit `~/.config/sops/age/keys.txt`.** Add `**/age/keys.txt` to your global gitignore for belt-and-braces.

## 2. Workflow

| Task | Command |
|------|---------|
| Decrypt `dev/atms.env.sops` to `.env` (gitignored) | `make secrets-decrypt ENV=dev` |
| Edit an encrypted file in `$EDITOR` | `make secrets-edit ENV=dev FILE=atms.env.sops` |
| Encrypt a plaintext file in place | `make secrets-encrypt ENV=dev FILE=atms.env` |
| Re-encrypt every SOPS file after `.sops.yaml` change | `make secrets-rotate-recipients` |
| Local check: are committed `*.sops*` files actually encrypted? | `make secrets-check` |

`make secrets-check` also runs in CI on every PR — see `.github/workflows/ci.yml`.

## 3. Adding a new secret

1. `make secrets-decrypt ENV=dev` to get a working `.env`.
2. Add the new `KEY=VALUE` line.
3. Save the plaintext as `deploy/secrets/dev/atms.env`:
   ```bash
   cp .env deploy/secrets/dev/atms.env
   ```
4. Encrypt and remove the plaintext:
   ```bash
   make secrets-encrypt ENV=dev FILE=atms.env
   ```
5. `git diff` should show only changes to `deploy/secrets/dev/atms.env.sops`. Commit it.
6. `make secrets-check` must pass. CI re-runs it.

The keys the SOPS config encrypts are controlled by `encrypted_regex` in `.sops.yaml` — by default any field matching `*PASSWORD*`, `*SECRET*`, `*TOKEN*`, `*KEY*`, or under `data:` / `stringData:` in a Kubernetes manifest. Hostnames, ports, and non-sensitive config stay readable in the diff.

## 4. Rotating an age recipient

Two situations:

### 4.1 Adding a new developer
1. Receive their public key (`age1...`) via a trusted channel.
2. Edit `.sops.yaml`, add the key to the `age:` list under the relevant `path_regex`.
3. `make secrets-rotate-recipients`.
4. Commit `.sops.yaml` and every modified `*.sops*` file in the same PR.
5. The new developer pulls and runs `make secrets-decrypt ENV=dev` to verify.

### 4.2 Revoking a developer (or a leaked key)
1. Generate **new** plaintext values for every secret (treat the old ones as compromised — they were decryptable by the revoked party).
2. Edit `.sops.yaml`, remove the leaving developer's age public key.
3. `make secrets-rotate-recipients`.
4. Re-encrypt with the new values via `make secrets-encrypt` per file.
5. Roll the actual credentials in the upstream systems (Postgres password, Kafka SASL, OIDC client secret, etc.). **The git history still contains the old encrypted form, which the revoked party can still decrypt** — only key rotation in the actual systems closes the gap.
6. Commit. Notify the team. Open a security-incident ticket.

## 5. Production cluster integration (Flux + SOPS)

Per [ADR-0003](../adr/0003-deployment-target-on-prem-k8s.md), the production cluster is on-prem Kubernetes managed by Flux. Flux's `kustomize-controller` decrypts SOPS files at sync time.

### One-time cluster bootstrap

```bash
# 1. Generate a cluster-bound age keypair. Store the PRIVATE key in an HSM
#    or sealed file; the PUBLIC key goes in .sops.yaml under the `prod:` block.
age-keygen -o cluster-age.txt

# 2. Create a Secret holding the private key, only readable by Flux.
kubectl -n flux-system create secret generic sops-age \
    --from-file=age.agekey=cluster-age.txt

# 3. Reference it from the Flux Kustomization resource.
#    (lives in the Flux bootstrap repo, NOT here)
```

### Per-environment kustomization

```yaml
# Excerpt from a Flux Kustomization (in your bootstrap repo):
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: atms-dev
  namespace: flux-system
spec:
  decryption:
    provider: sops
    secretRef:
      name: sops-age
  path: ./k8s/overlays/dev
  sourceRef:
    kind: GitRepository
    name: atms
```

The decryption happens transparently — pods see plaintext `Secret` objects mounted as env vars or files. The Git source-of-truth stays encrypted.

## 6. CI gates

| Job | What it checks |
|-----|----------------|
| `secrets-scan` (gitleaks) | No plaintext secrets in the diff. Uses `.gitleaks.toml` for ATMS-specific patterns (`AUTH_HS256_SECRET=`, `POSTGRES_PASSWORD=`, `AGE-SECRET-KEY-...`). |
| `secrets-check` (Makefile) | Every committed `*.sops*` file under `deploy/secrets/` looks encrypted (or is an explicit `PLACEHOLDER`). |

Both are blocking — a PR cannot merge if either fails. See [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).

## 7. Suspected leak — incident response

If you accidentally committed plaintext or believe a private age key has leaked:

1. **Do not** rewrite git history to "delete" the secret. It's already in clones, mirrors, and possibly forks.
2. **Rotate the underlying credential immediately.** Change the Postgres password, the OIDC client secret, the Kafka SASL password — whatever the leaked value was.
3. **Rotate the age recipient** as in §4.2.
4. Open an incident ticket with the SHA of the leaking commit, the credential rotated, and the rotation timestamp.
5. Notify `@OWNER-security` (per `CODEOWNERS`).

## 8. What NOT to do

- Do **not** disable `secrets-check` or `gitleaks` to make a PR pass. Fix the root cause.
- Do **not** commit `.env`, `atms.env`, or anything matching `**/age/keys.txt`.
- Do **not** share your personal age private key over Slack, email, or any chat.
- Do **not** use the dev age key in production. Each environment has its own recipient list per `.sops.yaml`.
- Do **not** assume "revoking" a recipient is sufficient — see §4.2.
