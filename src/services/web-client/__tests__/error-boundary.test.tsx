import React from "react";
import { vi, describe, it, expect, beforeAll, afterAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "@/components/error-boundary";

const mockNotifyError = vi.fn();

vi.mock("@/contexts/notification-context", () => ({
	useNotification: () => ({
		error: mockNotifyError,
		success: vi.fn(),
		info: vi.fn(),
		warning: vi.fn(),
	}),
}));

const ProblemChild = () => {
	throw new Error("Crash!");
};

describe("ErrorBoundary", () => {
	const originalConsoleError = console.error;

	beforeAll(() => {
		console.error = vi.fn();
	});

	afterAll(() => {
		console.error = originalConsoleError;
	});

	beforeEach(() => {
		mockNotifyError.mockClear();
	});

	it("renders the fallback UI when a child throws an error", () => {
		render(
			<ErrorBoundary>
				<ProblemChild />
			</ErrorBoundary>
		);

		expect(
			screen.getByText(/something went wrong\. please try again\./i)
		).toBeInTheDocument();
	});

	it("calls notifyError when a child throws an error", () => {
		render(
			<ErrorBoundary>
				<ProblemChild />
			</ErrorBoundary>
		);

		expect(mockNotifyError).toHaveBeenCalledWith(
			"An unexpected error occurred. Please reload the page."
		);
	});
});
