'use client';

import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, FileInput, Group, SimpleGrid, Text } from "@mantine/core";
import { IconAlertCircle, IconCheck, IconKey, IconRefresh } from "@tabler/icons-react";
import { userApi } from "@/lib/users/api";
import type { LicenseInfo, LicenseUploadResponse } from "@/lib/users/api";

const MAX_LICENSE_BYTES = 16 * 1024;

function LicenseFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="sm" className="break-words">{value}</Text>
    </div>
  );
}

export default function AdminLicensePage() {
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [result, setResult] = useState<LicenseUploadResponse | null>(null);
  const [licenseInfo, setLicenseInfo] = useState<LicenseInfo | null>(null);
  const [isLoadingInfo, setIsLoadingInfo] = useState(true);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadLicenseInfo = useCallback(async () => {
    setIsLoadingInfo(true);
    setInfoError(null);
    const response = await userApi.getLicenseInfo();
    if (!response.ok || !response.data) {
      setInfoError(response.error ?? "Could not load license status.");
    } else {
      setLicenseInfo(response.data);
    }
    setIsLoadingInfo(false);
  }, []);

  useEffect(() => {
    void loadLicenseInfo();
  }, [loadLicenseInfo]);

  const installLicense = async () => {
    if (!file) {
      setError("Select a license file first.");
      return;
    }
    if (file.size > MAX_LICENSE_BYTES) {
      setError("The license file must be 16 KiB or smaller.");
      return;
    }

    setIsUploading(true);
    setError(null);
    setResult(null);
    try {
      const response = await userApi.uploadLicense(file);
      if (!response.ok || !response.data) {
        setError(response.error ?? "The license could not be installed.");
        return;
      }
      setResult(response.data);
      await loadLicenseInfo();
    } catch {
      setError("A network error prevented the license upload.");
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <main className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-xl font-semibold text-[var(--text)]">License</h1>
        <p className="mt-1 text-sm text-[var(--textSoft)]">
          Install a signed Horus license file to test the license verification backend.
        </p>
      </div>

      <Card
        withBorder
        radius="md"
        className="max-w-2xl border-white/10 bg-[var(--bgSoft)]"
      >
        <div className="space-y-4">
          <Text size="sm" c="dimmed">
            Choose a compact signed license file (.jws). The server accepts files up to 16 KiB.
          </Text>
          <div className="space-y-1 rounded-md border border-white/10 p-3">
            <Group justify="space-between">
              <Text size="sm" fw={600}>Current license state</Text>
              <Button
                variant="subtle"
                size="xs"
                leftSection={<IconRefresh size={14} />}
                onClick={() => void loadLicenseInfo()}
                loading={isLoadingInfo}
              >
                Refresh
              </Button>
            </Group>
            {infoError && <Text size="sm" c="red">{infoError}</Text>}
            {licenseInfo && (
              <>
                <Text size="sm">State: {licenseInfo.state}</Text>
                {licenseInfo.reason && (
                  <Text size="sm" c="dimmed">{licenseInfo.reason}</Text>
                )}
                <Text size="xs" c="dimmed" className="break-all">
                  Installation site ID: {licenseInfo.site_id}
                </Text>
                <Text size="xs" c="dimmed">
                  The license issuer must include this site ID in the signed license.
                </Text>
                {licenseInfo.license ? (
                  <div className="space-y-3 border-t border-white/10 pt-3">
                    <Text size="sm" fw={600}>Verified license details</Text>
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                      <LicenseFact
                        label="Customer"
                        value={licenseInfo.license.customer_name}
                      />
                      <LicenseFact
                        label="Customer ID"
                        value={licenseInfo.license.customer_id}
                      />
                      <LicenseFact
                        label="License ID"
                        value={licenseInfo.license.license_id}
                      />
                      <LicenseFact
                        label="License type"
                        value={licenseInfo.license.license_type}
                      />
                      <LicenseFact
                        label="Tier"
                        value={licenseInfo.license.tier}
                      />
                      <LicenseFact
                        label="User cap"
                        value={
                          licenseInfo.license.user_cap === null
                            ? "Unlimited"
                            : String(licenseInfo.license.user_cap)
                        }
                      />
                      <LicenseFact
                        label="Valid from"
                        value={licenseInfo.license.valid_from}
                      />
                      <LicenseFact
                        label="Valid until"
                        value={licenseInfo.license.valid_until}
                      />
                      <LicenseFact
                        label="Issued at (UTC)"
                        value={licenseInfo.license.issued_at}
                      />
                      <LicenseFact
                        label="Grace period"
                        value={`${licenseInfo.license.grace_days} days`}
                      />
                      <LicenseFact
                        label="Authorized site IDs"
                        value={licenseInfo.license.site_ids.join(", ")}
                      />
                      <LicenseFact
                        label="Features"
                        value={licenseInfo.license.features.join(", ")}
                      />
                    </SimpleGrid>
                  </div>
                ) : (
                  <Text size="sm" c="dimmed">
                    No verified license claims are currently available.
                  </Text>
                )}
              </>
            )}
          </div>
          <FileInput
            label="License file"
            placeholder="Choose a .jws file"
            accept=".jws,application/jose"
            value={file}
            onChange={(nextFile) => {
              setFile(nextFile);
              setError(null);
              setResult(null);
            }}
            clearable
          />
          <Group justify="space-between" align="center">
            <Text size="sm" c="dimmed">
              {file ? `${(file.size / 1024).toFixed(1)} KiB` : "No file selected"}
            </Text>
            <Button
              leftSection={<IconKey size={16} />}
              onClick={() => void installLicense()}
              loading={isUploading}
              disabled={!file || isUploading}
            >
              Install license
            </Button>
          </Group>
          {error && (
            <Alert
              color="red"
              icon={<IconAlertCircle size={16} />}
              title="Installation failed"
              role="alert"
            >
              {error}
            </Alert>
          )}
          {result && (
            <Alert
              color="green"
              icon={<IconCheck size={16} />}
              title="License installed"
              role="status"
            >
              {result.message} Current state: {result.state}.
            </Alert>
          )}
        </div>
      </Card>
    </main>
  );
}
