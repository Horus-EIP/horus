import subprocess
import sys
from pathlib import Path
from uuid import UUID

from licensing.verification import LicenseState, verify_license

SITE_ID = "018f0f6a-7b2c-7d5a-9b8c-0123456789ad"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPOSITORY_ROOT / "scripts" / "generate_test_license.py"


def run_generator(tmp_path, *arguments):
    output_path = tmp_path / "test-license.jws"
    completed = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            SITE_ID,
            "--out",
            str(output_path),
            *arguments,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
        cwd=REPOSITORY_ROOT,
    )
    output_lines = completed.stdout.splitlines()
    key_id = next(
        line.removeprefix("HORUS_LICENSE_KID=")
        for line in output_lines
        if line.startswith("HORUS_LICENSE_KID=")
    )
    public_key_hex = next(
        line.removeprefix("HORUS_LICENSE_PUBKEY_HEX=")
        for line in output_lines
        if line.startswith("HORUS_LICENSE_PUBKEY_HEX=")
    )
    return output_path.read_text(encoding="ascii"), key_id, public_key_hex, completed.stdout


def test_generated_test_license_verifies_for_its_site(tmp_path):
    token, key_id, public_key_hex, output = run_generator(tmp_path)
    result = verify_license(
        token,
        {key_id: bytes.fromhex(public_key_hex)},
        SITE_ID,
    )

    assert "NEVER USE IN PRODUCTION" in output
    assert result.state is LicenseState.VALID
    assert result.claims is not None
    assert result.claims.site_ids == (UUID(SITE_ID),)
    assert result.claims.customer_name == "Horus Local Test"


def test_generated_recovery_license_contains_the_requested_nonce(tmp_path):
    nonce = "018f0f6a-7b2c-7d5a-9b8c-0123456789ab"
    token, key_id, public_key_hex, _ = run_generator(
        tmp_path,
        "--rollback-nonce",
        nonce,
    )

    result = verify_license(
        token,
        {key_id: bytes.fromhex(public_key_hex)},
        SITE_ID,
    )

    assert result.state is LicenseState.VALID
    assert result.claims is not None
    assert result.claims.clock_reset_nonce == UUID(nonce)


def test_generator_rejects_invalid_site_uuid(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "not-a-uuid"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=REPOSITORY_ROOT,
    )

    assert completed.returncode == 2
    assert "site_id" in completed.stderr
