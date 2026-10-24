'use client';

import { apiClient } from "@/lib/api-client";
import type { ApiResponse } from "@/lib/api-client";

export interface LicenseUploadResponse {
  message: string;
  state: string;
}

export interface LicenseInfo {
  site_id: string;
  state: string;
  reason: string | null;
  license: LicenseSummary | null;
  active_user_count?: number;
  is_capped?: boolean;
}

export interface LicenseSummary {
  license_id: string;
  license_type: string;
  customer_id: string;
  customer_name: string;
  site_ids: string[];
  tier: string;
  user_cap: number | null;
  issued_at: string;
  valid_from: string;
  valid_until: string;
  grace_days: number;
  features: string[];
}

export const licenseApi = {
  async getLicenseInfo(): Promise<ApiResponse<LicenseInfo>> {
    return apiClient.get<LicenseInfo>("/license/status");
  },

  async uploadLicense(file: File): Promise<ApiResponse<LicenseUploadResponse>> {
    const formData = new FormData();
    formData.append("file", file);
    return apiClient.postMultipart<LicenseUploadResponse>(
      "/license/upload",
      formData
    );
  },
};
