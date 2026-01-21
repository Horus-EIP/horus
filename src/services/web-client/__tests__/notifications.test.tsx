import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { NotificationProvider, useNotification } from "@/contexts/notification-context";

const TestComponent = () => {
  const { success, error } = useNotification();

  return (
    <div>
      <button onClick={() => success("Saved!")}>Success</button>
      <button onClick={() => error("Failed!")}>Error</button>
    </div>
  );
};

describe("NotificationProvider & Toast", () => {
  it("shows success toast when success() is called", async () => {
    render(
      <NotificationProvider>
        <TestComponent />
      </NotificationProvider>
    );

    fireEvent.click(screen.getByText("Success"));

    expect(await screen.findByText("Saved!")).toBeInTheDocument();
  });

  it("shows error toast when error() is called", async () => {
    render(
      <NotificationProvider>
        <TestComponent />
      </NotificationProvider>
    );

    fireEvent.click(screen.getByText("Error"));

    expect(await screen.findByText("Failed!")).toBeInTheDocument();
  });
});
