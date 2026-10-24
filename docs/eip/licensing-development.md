# Licensing Implementation and Local Development

This guide describes the current MAS licensing implementation, local test
licence workflow, persistent state, and CI validation. For the signed payload
contract, see [the licence file format](./license-key-format.md). For state
transitions and feature access, see [the licensing rules](./licensing-rules.md).

## Implementation map

| Concern | Implementation |
|---|---|
| JWS parsing, Ed25519 signature verification, claim validation, and state evaluation | `src/services/mas/licensing/verification.py` |
| Trusted public-key construction | `src/services/mas/licensing/config.py`, called by the shared environment settings in `src/services/mas/core/config.py` |
| Persistent installation `site_id` | `src/services/mas/licensing/site.py` and `src/services/mas/licensing/models/global_config.py` |
| Clock high-water mark and one-time recovery nonces | `src/services/mas/licensing/clock.py` and `src/services/mas/licensing/models/clock_state.py` |
| License status, upload, and live status endpoints | `src/services/mas/licensing/routes.py` |
| Core feature access and registration cap | `src/services/mas/licensing/access.py` |
| Startup license initialization | `src/services/mas/licensing/lifecycle.py`, invoked by `src/services/mas/core/app.py` |
| Local-only test licence generator | `scripts/generate_test_license.py` |

The SQLAlchemy models live with the licensing domain and are re-exported by
`db.models` so Alembic includes them in the shared metadata. Schema revisions
remain in `src/services/mas/db/alembic/versions`, where the migration runner
expects to find them. License-related environment variables remain declared
in the shared MAS settings class; parsing the trusted public key is isolated in
the licensing package.

## Runtime configuration

MAS reads these values from its environment:

| Variable | Purpose |
|---|---|
| `HORUS_LICENSE_PATH` | Filesystem path to the compact JWS license. Compose mounts the configured license directory into the MAS container. |
| `HORUS_LICENSE_KID` | Trusted key identifier; it must exactly match the JWS protected-header `kid`. |
| `HORUS_LICENSE_PUBKEY_HEX` | Trusted raw Ed25519 public key as exactly 64 hexadecimal characters (32 decoded bytes). |

The signing private key is not a MAS setting. Never put it in the repository,
`.env`, a container, or the customer installation. A missing public key results
in an empty trusted-key set; malformed or incorrectly sized values are
configuration errors.

The Compose example uses `/run/horus/license/licence.jws` as the container path.
When changing the path or mount, make sure the setting and mounted file location
refer to the same file.

## Installation identity and API workflow

The installation `site_id` identifies one Horus database installation. It is
independent of the licence file: no certificate or `.jws` needs to exist for
MAS to create or return the ID. The first successful license-status request
creates a UUID and persists it in the `global_config` singleton row. Later
requests return that same value. Concurrent first requests are handled by the
database uniqueness constraint and the helper's insert-race recovery.

The ID is database state, not container-local state. Preserve the database
across container replacement, upgrades, and restores to preserve the ID. If
the database is deliberately reinitialized or the installation configuration
row is deleted, a new ID is generated; a licence tied to the previous ID will
not match and must be reissued for the new installation identity. Do not copy
an ID from another deployment.

`GET /users/license` requires an authenticated account with
system-configuration permission and initialized license state in the MAS
application. It returns:

| Field | Meaning |
|---|---|
| `site_id` | Persistent installation UUID, available whether or not a licence is installed. |
| `state` | Current evaluated license state, such as `missing`, `valid`, or `restricted`. |
| `reason` | Optional verifier/configuration explanation for the current state. |
| `license` | `null` when verified claims are unavailable; otherwise a summary of signed claims. |

When present, `license` includes the license ID and type, customer ID and
name, authorized site IDs, tier, user cap, issue and validity dates, grace
period, and features. It does not include recovery nonces, signature bytes,
private key material, or the raw JWS. The Admin → License page displays the
site ID and state even when `license` is `null`; it renders the claims summary
only when verified claims are available. This page is an administrative view,
not a substitute for the verifier or feature-access checks.

A newly issued license must include the exact installation UUID in its signed
`site_ids` claim. The site ID shown on the License page is the value to provide
to the authorized issuer; do not generate one manually or copy one from a
different environment.

`POST /users/upload-license` accepts a multipart file upload from an account
with system-configuration permission. MAS limits the file to 16 KiB, verifies
the signature and claims against the configured public key and installation
ID, evaluates the state, and persists the clock state with the installed file.
Invalid signatures and claims are rejected; an invalid new file does not become
the installed licence.

The status endpoint is the source of truth for the installation ID and loaded
licence state. If the endpoint returns `503`, the application license state
has not been initialized; this is different from a missing license, where the
endpoint can return the persisted site ID and a `missing` state.

## Generate and install a local test licence

The generator creates a fresh Ed25519 key pair for each invocation. It writes
the compact signed JWS and prints the matching public-key configuration. The
private key is neither printed nor saved; after the process exits, that signer
cannot issue another licence. The default key ID is `horus-test-v1`, deliberately
distinct from the production-looking ID used in deployment examples.

1. Read the `site_id` from the local MAS `GET /users/license` endpoint.
2. Generate a local test file:

   ```bash
   python scripts/generate_test_license.py \
     018f0f6a-7b2c-7d5a-9b8c-0123456789ad \
     --out src/infra/license/test-license.jws
   ```

   Replace the example UUID with the ID returned by that local installation.
3. Set the printed `HORUS_LICENSE_KID` and `HORUS_LICENSE_PUBKEY_HEX` values
   only in the local test environment. Ensure `HORUS_LICENSE_PATH` resolves to
   the generated file inside MAS.
4. Upload the file through the admin license page or
   `POST /users/upload-license`, then confirm the reported state is `valid` or
   `warning`.

The generated licence is valid for one site, uses the Starter cap, and is
intended only for local development. Running the script again creates a
different key pair; the previous JWS will no longer verify if the configured
public key is replaced. The output JWS is not production-ready, even if it is
uploaded successfully.

To exercise clock-recovery behavior locally, provide a UUID with
`--rollback-nonce`. This only adds a signed claim; it does not itself cause a
clock rollback. A recovery upload must be tested against a simulated or
controlled rollback condition. A successfully accepted nonce is persisted and
cannot be reused.

## Persistent clock and recovery state

`license_clock_state` stores the highest observed UTC time. A current time more
than 48 hours behind that high-water mark yields `clock_rollback`. Normal
verification is pure; callers supply the current time and persisted clock.

`consumed_reset_nonces` stores UUID recovery tokens to reject replay. The table
is created by the Alembic migration
`8e48716efaad_add_consumed_reset_nonces_table_for_license_rollback_recovery`.
The MAS entrypoint runs `alembic upgrade head` before starting the application.

During a recovery upload, MAS validates the signed nonce, records it, resets
the high-water mark, and verifies the licence again before installation. The
upload code attempts to restore the previous licence file if a handled database
or filesystem error occurs. A database transaction and filesystem rename are
not one atomic transaction, so this rollback does not protect against every
process or machine failure between the two operations.

## Access behavior

Chat, agents, and tasks use `require_active_license`. Administrative operations
remain reachable according to their permission checks; the JSON data export
route is deliberately exempt from the license gate but still requires the
export permission. See the feature matrix in
[the licensing rules](./licensing-rules.md).

Account registration is allowed only in `valid`, `warning`, or `grace` states.
It is denied when the license is missing, invalid, not yet valid, restricted,
or in clock rollback. When a finite cap is configured, the current route counts
all user rows before allowing registration.

The shared `require_active_license` dependency allows only `valid`, `warning`,
and `grace`. Missing application state returns `503`; all other non-active
states return `403`.

The rules document describes the intended cap in terms of active accounts.
Current account creation code compares the total number of user rows against
the cap. It does not currently filter that count by `is_active`; do not treat
inactive-account exclusion as implemented behavior.

## CI validation

The MAS CI job runs the full non-stack test suite with branch coverage:

```bash
pytest -c tests/mas/pytest.ini tests/mas \
  -m "not requires_stack" \
  --ignore=tests/mas/test_integration.py \
  --cov=src/services/mas \
  --cov-branch \
  --cov-fail-under=85 \
  --cov-report=xml:coverage-mas.xml \
  --cov-report=term-missing \
  --cov-report=html:htmlcov-mas \
  --junitxml=junit-mas.xml
```

The repository Ruff CI job runs:

```bash
ruff check src tests scripts installer packaging opensource
```

The CI MAS tests use SQLite and mocked services; they do not apply migrations to
a running PostgreSQL stack. Stack-dependent tests are marked
`requires_stack` and excluded from the MAS CI command above.
