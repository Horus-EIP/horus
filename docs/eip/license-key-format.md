# Horus Offline Licence File Format

**Related:** [Licensing rules](./licensing-rules.md), [ADR-004](../adr/ADR-004-closed-source-licence.md)
**Scope:** File format and validation contract. See [Licensing implementation and local development](./licensing-development.md) for the implementation map, local test workflow, and CI commands.

## 1. Format decisions

- A licence file is a compact JWS containing a JSON payload.
- The JWS algorithm is EdDSA using Ed25519. The verifier trusts only configured public keys; signing private keys never belong in Horus, this repository, or CI.
- The protected JWS header contains the algorithm, a fixed type, and a key identifier (`kid`).
- The file is at most 16 KiB and contains only the compact token: no BOM, whitespace, or line breaks.
- The payload uses `format_version: 1`. Unsupported versions are rejected; they are never interpreted as version 1.
- `license_type` distinguishes `commercial` from `evaluation`.
- `site_ids` is an explicit allowlist. Starter and Team licences authorize exactly one site; Enterprise licences authorize one or more sites.
- User caps, validity dates, grace duration, and warnings follow `licensing-rules.md`. For version 1, `user_cap` is fixed by tier and `grace_days` is 15.

## 2. JWS serialization

The file is UTF-8 text containing one compact JWS:

```text
BASE64URL(protected-header).BASE64URL(payload).BASE64URL(signature)
```

The signature is Ed25519 over the JWS signing input defined by RFC 7515: the ASCII bytes of `BASE64URL(protected-header) + "." + BASE64URL(payload)`. Base64url segments use the JWS encoding (URL-safe alphabet, without `=` padding). The payload is UTF-8 JSON. No re-serialization or JSON canonicalization is performed before signature verification.

The protected header must contain exactly:

```json
{
  "alg": "EdDSA",
  "kid": "horus-prod-2026-01",
  "typ": "HORUS-LICENSE"
}
```

`kid` selects a public key from Horus's trusted-key set. Unknown key IDs, duplicate JSON object keys, unsupported header parameters, a different `alg` or `typ`, malformed base64url, or a signature that is not a valid Ed25519 signature cause rejection. The verifier must not select an algorithm based on untrusted input; it accepts only the fixed `EdDSA` algorithm.

## 3. Version 1 payload schema

The payload is a JSON object with exactly the following fields:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Horus Offline Licence Payload v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "format_version",
    "license_id",
    "license_type",
    "customer_id",
    "customer_name",
    "site_ids",
    "tier",
    "user_cap",
    "issued_at",
    "valid_from",
    "valid_until",
    "grace_days",
    "features"
  ],
  "properties": {
    "format_version": { "const": 1 },
    "license_id": { "type": "string", "format": "uuid" },
    "license_type": { "enum": ["commercial", "evaluation"] },
    "customer_id": { "type": "string", "format": "uuid" },
    "customer_name": { "type": "string", "minLength": 1, "maxLength": 200 },
    "site_ids": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": { "type": "string", "format": "uuid" }
    },
    "tier": { "enum": ["starter", "team", "enterprise"] },
    "user_cap": { "oneOf": [{ "type": "integer", "minimum": 1 }, { "type": "null" }] },
    "issued_at": { "type": "string", "format": "date-time", "pattern": "Z$" },
    "valid_from": { "type": "string", "format": "date" },
    "valid_until": { "type": "string", "format": "date" },
    "grace_days": { "const": 15 },
    "features": {
      "type": "array",
      "minItems": 1,
      "uniqueItems": true,
      "items": { "enum": ["core"] }
    }
  }
}
```

The JSON Schema is a structural baseline. A conforming verifier also applies these semantic rules:

| Field/rule | Version 1 constraint |
|---|---|
| IDs | UUIDs identify a licence, customer, and deployment site. `license_id` is unique per issued licence. |
| `tier` / `user_cap` | `starter` requires `25`; `team` requires `100`; `enterprise` requires `null` (unlimited). Any mismatch is invalid. |
| `site_ids` | Starter and Team require exactly one site ID. Enterprise may contain one or more site IDs. The running installation's site ID must be present. |
| `issued_at` | RFC 3339 UTC timestamp ending in `Z`; fractional seconds are permitted. It records when the issuer created the licence and is not a substitute for the validity interval. |
| `valid_from` | ISO 8601 calendar date, inclusive from `00:00:00 UTC` on that date. |
| `valid_until` | ISO 8601 calendar date, inclusive. The licence expires at `00:00:00 UTC` on the following date. It must be on or after `valid_from`. |
| `grace_days` | Must equal 15. Grace starts at the expiration instant and ends 15 days later, at `00:00:00 UTC`; at that instant the state is `restricted`. |
| `license_type` | `commercial` follows the signed validity interval. `evaluation` is non-production and may span no more than 90 calendar days (`valid_until` minus `valid_from` must be less than 90 days). |
| `features` | Version 1 supports only `core`. Unknown feature identifiers are rejected, not silently ignored. |
| Dates and times | Parse and compare in UTC. A verifier must enable JSON Schema format checking or equivalent strict parsing; merely accepting the `format` annotation is insufficient. |

The expiry and grace instants are derived from the dates and `grace_days`; they are not duplicated in the payload. Warnings are derived from `valid_until` and use the thresholds in `licensing-rules.md`.

## 4. Example payload

This is an example of a structurally and semantically valid payload. It is **not a usable licence** by itself: the issuer must sign it with an authorized private key and distribute the resulting compact JWS.

```json
{
  "format_version": 1,
  "license_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ab",
  "license_type": "commercial",
  "customer_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ac",
  "customer_name": "Example Customer",
  "site_ids": ["018f0f6a-7b2c-7d5a-9b8c-0123456789ad"],
  "tier": "team",
  "user_cap": 100,
  "issued_at": "2026-10-23T17:00:00Z",
  "valid_from": "2026-10-23",
  "valid_until": "2027-01-22",
  "grace_days": 15,
  "features": ["core"]
}
```

## 5. Rejection cases

A verifier rejects a file if any of the following applies:

- It is not exactly a three-segment compact JWS, cannot be decoded, or exceeds 16 KiB.
- The header is not the required EdDSA licence header, `kid` is unknown, or signature verification fails.
- The payload is not valid UTF-8 JSON, contains duplicate keys, has missing or unknown fields, or fails the version 1 schema.
- An ID, date, timestamp, enum, or feature is malformed or unsupported.
- Tier and cap disagree; site count violates the tier rule; the installation site is not listed; or `valid_until` precedes `valid_from`.
- An evaluation licence spans more than 90 calendar days.
- The licence is authentic but not currently valid. In that case the verifier reports the corresponding state (`not_yet_valid`, `grace`, or `restricted`) rather than treating it as a signature/schema failure.

Invalid signatures, unknown `kid` values, malformed payloads, and unsupported schema versions must fail closed. They must not fall back to unsigned fields or another algorithm.

### Invalid examples and expected result

| Invalid input | Expected result |
|---|---|
| A valid-looking payload with `user_cap: 25` and `tier: "team"` | Reject as semantically invalid; do not treat it as a Starter licence. |
| A Starter payload with two `site_ids` | Reject because Starter authorizes exactly one site. |
| An evaluation payload whose dates span 90 days or more | Reject as invalid; the maximum is 89 days between the two dates (90 calendar dates inclusive). |
| A payload with `features: ["core", "marketplace"]` | Reject the unsupported feature; do not silently grant or ignore it. |
| The valid example payload with any byte changed after signing | Reject because Ed25519 signature verification fails. |
| A correctly signed payload with `format_version: 2` | Reject as unsupported; never parse it as version 1. |

## 6. Compatibility and key rotation

Version 1 is strict: unknown payload fields, header parameters, algorithms, and feature IDs are rejected. Any incompatible format change requires a new `format_version` and migration/compatibility policy as described in `VERSIONING.md`.

The trusted-key set may contain multiple public keys during rotation. New licences use the current `kid`; existing licences remain verifiable while their `kid` remains trusted. Removing an old public key is an explicit operational change and must account for still-valid licences. Production private-key generation, custody, backup, and signing procedures are outside this repository-facing file format and must be documented separately without exposing private key material. The repository's local test generator is not a production issuer.

## 7. Scope not decided by this format

- The production issuer's private-key custody, signing tool, recovery ceremony, and authorization workflow. The repository includes only a local test generator.
- How the site's stable UUID is created, displayed, backed up, or moved to replacement hardware.
- How `evaluation` is prevented from being used in production; the claim records the contract restriction, but offline software cannot independently prove the customer's environment or intent.
- The persistence and recovery mechanism for `last_seen_clock`. `issued_at` is signed issuance metadata; it does not by itself authorize resetting the clock high-water mark.
- The API or UI used to install/renew a licence and the admin/export behavior for invalid or missing licences.
