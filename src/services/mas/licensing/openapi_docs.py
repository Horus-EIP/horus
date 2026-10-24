"""OpenAPI response models and examples for the license API."""

from typing import Literal

from pydantic import BaseModel, Field

LicenseStateValue = Literal[
    "missing",
    "invalid",
    "not_yet_valid",
    "valid",
    "warning",
    "grace",
    "restricted",
    "clock_rollback",
]
LicenseTier = Literal["starter", "team", "enterprise"]


class LicenseClaimsSummary(BaseModel):
    license_id: str = Field(
        examples=["018f0f6a-7b2c-7d5a-9b8c-0123456789ab"],
        json_schema_extra={"format": "uuid"},
    )
    license_type: Literal["commercial", "evaluation"] = Field(
        examples=["commercial"]
    )
    customer_id: str = Field(
        examples=["018f0f6a-7b2c-7d5a-9b8c-0123456789ac"],
        json_schema_extra={"format": "uuid"},
    )
    customer_name: str = Field(examples=["Example Customer"])
    site_ids: list[str] = Field(
        examples=[["018f0f6a-7b2c-7d5a-9b8c-0123456789ad"]],
        json_schema_extra={"items": {"format": "uuid"}},
    )
    tier: LicenseTier = Field(examples=["team"])
    user_cap: int | None = Field(examples=[100])
    issued_at: str = Field(
        examples=["2026-10-24T12:00:00+00:00"],
        json_schema_extra={"format": "date-time"},
    )
    valid_from: str = Field(
        examples=["2026-01-01"],
        json_schema_extra={"format": "date"},
    )
    valid_until: str = Field(
        examples=["2026-12-31"],
        json_schema_extra={"format": "date"},
    )
    grace_days: int = Field(examples=[15])
    features: list[Literal["core"]] = Field(examples=[["core"]])


class LicenseStatusResponse(BaseModel):
    site_id: str = Field(
        examples=["018f0f6a-7b2c-7d5a-9b8c-0123456789ad"],
        json_schema_extra={"format": "uuid"},
    )
    state: LicenseStateValue = Field(examples=["valid"])
    reason: str | None = Field(default=None, examples=[None])
    license: LicenseClaimsSummary | None


class LicenseUploadResponse(BaseModel):
    message: str = Field(examples=["License installed successfully"])
    state: Literal["valid", "warning", "grace"] = Field(examples=["valid"])


class LicenseLiveStatusResponse(BaseModel):
    state: LicenseStateValue = Field(examples=["warning"])
    warning_threshold_days: Literal[1, 7, 14, 30] | None = Field(
        default=None, examples=[14]
    )
    tier: LicenseTier | None = Field(default=None, examples=["team"])
    features: list[Literal["core"]] = Field(default_factory=list, examples=[["core"]])


def error_response(description: str, detail: object) -> dict[str, object]:
    """Build the standard HTTPException response documentation with an example."""
    return {
        "description": description,
        "content": {
            "application/json": {
                "example": {"detail": detail},
            }
        },
    }


LICENSE_STATUS_RESPONSES = {
    200: {
        "description": "Current installation identity and evaluated license.",
        "content": {
            "application/json": {
                "examples": {
                    "withoutVerifiedLicense": {
                        "summary": "No verified license is currently loaded",
                        "value": {
                            "site_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ad",
                            "state": "missing",
                            "reason": "No licence file is configured.",
                            "license": None,
                        },
                    },
                    "verifiedLicense": {
                        "summary": "Verified license claims",
                        "value": {
                            "site_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ad",
                            "state": "valid",
                            "reason": None,
                            "license": {
                                "license_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ab",
                                "license_type": "commercial",
                                "customer_id": "018f0f6a-7b2c-7d5a-9b8c-0123456789ac",
                                "customer_name": "Example Customer",
                                "site_ids": [
                                    "018f0f6a-7b2c-7d5a-9b8c-0123456789ad"
                                ],
                                "tier": "team",
                                "user_cap": 100,
                                "issued_at": "2026-10-24T12:00:00+00:00",
                                "valid_from": "2026-01-01",
                                "valid_until": "2026-12-31",
                                "grace_days": 15,
                                "features": ["core"],
                            },
                        },
                    },
                }
            }
        },
    },
    401: error_response(
        "Authentication is missing, expired, or invalid.",
        "Not authenticated",
    ),
    403: error_response(
        "The authenticated user lacks system-configuration permission.",
        "Insufficient permissions",
    ),
    503: error_response(
        "License state has not been initialized in the application.",
        "License status is not initialized yet.",
    ),
}

LICENSE_UPLOAD_RESPONSES = {
    200: {
        "description": "License was verified, installed, and persisted.",
        "content": {
            "application/json": {
                "example": {
                    "message": "License installed successfully",
                    "state": "valid",
                }
            }
        },
    },
    400: error_response(
        "The uploaded license is invalid or clock-recovery validation failed.",
        "License rejected: Licence signature verification failed.",
    ),
    401: error_response(
        "Authentication is missing, expired, or invalid.",
        "Not authenticated",
    ),
    403: error_response(
        "The authenticated user lacks system-configuration permission.",
        "Insufficient permissions",
    ),
    413: error_response(
        "The uploaded license exceeds the 16 KiB limit.",
        "The file is too large. Maximum allowed: 16 KiB.",
    ),
    422: error_response(
        "The multipart request is invalid or does not contain a file field.",
        [
            {
                "type": "missing",
                "loc": ["body", "file"],
                "msg": "Field required",
                "input": None,
            }
        ],
    ),
    500: {
        "description": (
            "Trusted-key configuration is malformed, or database/filesystem "
            "operations prevented installation."
        ),
        "content": {
            "application/json": {
                "examples": {
                    "invalidPublicKey": {
                        "summary": "Malformed trusted public-key configuration",
                        "value": {
                            "detail": (
                                "HORUS_LICENSE_PUBKEY_HEX must be a hexadecimal "
                                "Ed25519 public key."
                            )
                        },
                    },
                    "installationFailure": {
                        "summary": "Database or filesystem installation failure",
                        "value": {
                            "detail": (
                                "License installation failed because of an "
                                "internal or file-system error."
                            )
                        },
                    },
                }
            }
        },
    },
    503: error_response(
        "No trusted license verification key is configured.",
        "No trusted license key is configured.",
    ),
}
