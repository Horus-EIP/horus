# FinCorp — IT Security Policy

**Version:** 5.0
**Effective date:** January 1, 2026
**Owner:** Priya Patel, Chief Information Security Officer (CISO)
**IT Director:** Alice Chen
**Classification:** INTERNAL

---

## 1. Scope

This policy applies to all FinCorp employees, contractors, and vendors with
access to FinCorp systems, data, or facilities.

## 2. Identity and Access

### 2.1 Password requirements

- **Minimum length:** 14 characters.
- Must include upper, lower, number, and symbol.
- No reuse of the last 12 passwords.
- Rotation: every **90 days** for privileged accounts, every **180 days** for
  standard accounts.
- Passwords are never to be shared, written down, or stored in unencrypted files.

### 2.2 Multi-factor authentication (MFA)

- MFA is **mandatory** for all accounts accessing FinCorp systems.
- Hardware tokens (YubiKey) required for privileged accounts (admins, finance,
  executives).
- SMS-based MFA is **not permitted** for any account.

### 2.3 Least privilege

- Access is granted on a need-to-know, need-to-use basis.
- Quarterly access reviews by system owners, due the last Friday of each quarter.
- Offboarding: all access revoked within **4 hours** of termination notification.

## 3. Device Security

- All laptops must have full-disk encryption (FileVault / BitLocker).
- Endpoint Detection & Response (EDR) agent mandatory on all company devices.
- Personal devices connecting to FinCorp email must enroll in MDM.
- USB storage is blocked by default; exceptions require CISO approval.

## 4. Network Security

- All remote access goes through the corporate VPN or Zero Trust gateway.
- Public Wi-Fi access to confidential data is prohibited without VPN.
- Network segmentation: production environments are isolated from corporate
  networks.

## 5. Data Handling

- Data classification follows the Compliance Guidelines (§7): Public, Internal,
  Confidential, Restricted.
- **Restricted** data (PII, client trading strategies) must be encrypted at
  rest (AES-256) and in transit (TLS 1.2+).
- No client data may be stored on personal devices or personal cloud accounts.

## 6. Incident Response

### 6.1 Reporting

Any suspected security incident must be reported to the IT Security team
within **1 hour** of discovery:

- Primary: security@fincorp.com
- On-call: +1 (555) 010-0199 (24/7)
- CISO: Priya Patel

### 6.2 Response SLAs

| Severity | Definition | Response SLA |
|----------|------------|-------------:|
| P1 — Critical | Active breach, client data exposure | 15 minutes |
| P2 — High | Confirmed malware, privileged account compromise | 1 hour |
| P3 — Medium | Phishing attempt, unauthorized access attempt | 4 hours |
| P4 — Low | Policy violation, lost non-sensitive device | 24 hours |

### 6.3 Breach notification

Personal data breaches are reported to the DPO (Michael Brown) immediately,
and to the supervisory authority within **72 hours** per GDPR.

## 7. AI System Security (Horus Platform)

The Horus multi-agent orchestration platform is classified as **Confidential**
and subject to:

- Self-hosted deployment on FinCorp infrastructure only.
- All uploaded documents inherit the classification of the source material.
- API keys rotated every **90 days** or immediately upon suspicion of compromise.
- Audit logs retained for **12 months**, accessible to Priya Patel and Michael Brown.
- DPIA due March 31, 2026, per Compliance Guidelines §2.

## 8. Training

- Security awareness training: mandatory on hire, annually thereafter.
- Phishing simulations: quarterly, run by Alice Chen (IT Director).
- Failure to complete training within 30 days suspends system access.

## 9. Enforcement

Violations of this policy are reported to HR (Rachel Garcia) and may result
in disciplinary action up to and including termination. Criminal violations
are reported to law enforcement in coordination with Michael Brown (Compliance).

---

Signed:
**Priya Patel**, Chief Information Security Officer
**Alice Chen**, IT Director
Date: December 28, 2025
