import React, { useState } from "react";
import { vi, describe, it, expect, beforeAll, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MantineProvider } from "@mantine/core";
import {
  FileAttachments,
  type FileAttachmentsValue,
} from "@/components/tasks/file-attachments";
import {
  knowledgeStoreApi,
  type KnowledgeStoreDocument,
} from "@/lib/knowledge-store/api";

const DUPLICATE_TITLE = "1_Q4_2025_Financial_Report.md";

const olderCopy: KnowledgeStoreDocument = {
  id: "7f3c9a1e2b4d4f6a8c0e1a2b3c4d5e6f",
  title: DUPLICATE_TITLE,
  date: "2026-09-20 08:15:42.123456+00:00",
  size: 2048,
};

const newerCopy: KnowledgeStoreDocument = {
  id: "c2d4e6f8a0b24c6e8a0c2e4f6a8b0c2d",
  title: DUPLICATE_TITLE,
  date: "2026-10-01 14:30:05.654321+00:00",
  size: 4096,
};

const otherDocument: KnowledgeStoreDocument = {
  id: "0a1b2c3d4e5f40718293a4b5c6d7e8f9",
  title: "Employee_Handbook.md",
  date: "2026-09-01 10:00:00.000000+00:00",
  size: 1024,
};

const emptyValue: FileAttachmentsValue = { attached: [], inline: [] };

function renderPicker(initial: FileAttachmentsValue = emptyValue) {
  const onChange = vi.fn();
  function Harness() {
    const [value, setValue] = useState<FileAttachmentsValue>(initial);
    return (
      <MantineProvider env="test">
        <FileAttachments
          value={value}
          onChange={(next) => {
            setValue(next);
            onChange(next);
          }}
        />
      </MantineProvider>
    );
  }
  render(<Harness />);
  return { onChange, user: userEvent.setup() };
}

async function openPicker(user: ReturnType<typeof userEvent.setup>) {
  const input = await screen.findByPlaceholderText("Pick one or more files…");
  await user.click(input);
  return screen.findAllByRole("option");
}

async function dropFile(
  user: ReturnType<typeof userEvent.setup>,
  file: File
) {
  await user.click(screen.getByRole("tab", { name: /upload new/i }));
  const input = document.querySelector<HTMLInputElement>('input[type="file"]');
  expect(input).not.toBeNull();
  await user.upload(input!, file);
  await screen.findByText("Save to the knowledge store?");
}

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  window.ResizeObserver = ResizeObserverStub;
  window.HTMLElement.prototype.scrollIntoView = () => {};
});

describe("regression F25 duplicate knowledge-store file names", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(knowledgeStoreApi, "listDocuments").mockResolvedValue({
      ok: true,
      data: [olderCopy, newerCopy],
    });
  });

  it("f25 lists two documents with the same title as two distinct options without crashing", async () => {
    const { user } = renderPicker();

    const options = await openPicker(user);

    expect(options).toHaveLength(2);
    options.forEach((option) =>
      expect(option).toHaveTextContent(DUPLICATE_TITLE)
    );
    expect(new Set(options.map((option) => option.textContent)).size).toBe(2);
  });

  it("f25 labels each copy with its upload date and size", async () => {
    const { user } = renderPicker();

    const options = await openPicker(user);

    expect(options.map((option) => option.textContent)).toEqual([
      `${DUPLICATE_TITLE} · uploaded 2026-09-20 08:15 UTC · 2.0 KB`,
      `${DUPLICATE_TITLE} · uploaded 2026-10-01 14:30 UTC · 4.0 KB`,
    ]);
  });

  it("f25 keeps a unique title as a plain label", async () => {
    vi.mocked(knowledgeStoreApi.listDocuments).mockResolvedValue({
      ok: true,
      data: [olderCopy, newerCopy, otherDocument],
    });
    const { user } = renderPicker();

    const options = await openPicker(user);

    expect(options.map((option) => option.textContent)).toContain(
      "Employee_Handbook.md"
    );
  });

  it("f25 keeps labels unique when copies share upload minute and size", async () => {
    vi.mocked(knowledgeStoreApi.listDocuments).mockResolvedValue({
      ok: true,
      data: [
        olderCopy,
        { ...olderCopy, id: "9e8d7c6b5a4940398271605f4e3d2c1b" },
      ],
    });
    const { user } = renderPicker();

    const options = await openPicker(user);

    expect(options).toHaveLength(2);
    expect(new Set(options.map((option) => option.textContent)).size).toBe(2);
  });

  it("f25 attaches the picked copy by document id and keeps its filename", async () => {
    const { user, onChange } = renderPicker();

    const options = await openPicker(user);
    const newer = options.find((option) =>
      option.textContent?.includes("2026-10-01")
    );
    await user.click(newer!);

    expect(onChange).toHaveBeenLastCalledWith({
      attached: [{ doc_id: newerCopy.id, filename: DUPLICATE_TITLE }],
      inline: [],
    });
  });

  it("f25 maps a filename-only attachment to one stored copy", async () => {
    const { user, onChange } = renderPicker({
      attached: [{ filename: DUPLICATE_TITLE }],
      inline: [],
    });

    const options = await openPicker(user);
    const selected = options.filter(
      (option) => option.getAttribute("aria-selected") === "true"
    );
    expect(selected).toHaveLength(1);

    const unselected = options.find((option) => !selected.includes(option));
    await user.click(unselected!);

    expect(onChange).toHaveBeenLastCalledWith({
      attached: [
        { doc_id: olderCopy.id, filename: DUPLICATE_TITLE },
        { doc_id: newerCopy.id, filename: DUPLICATE_TITLE },
      ],
      inline: [],
    });
  });

  it("f25 warns before upload when a file with the same name is already stored", async () => {
    const { user } = renderPicker();
    await screen.findByPlaceholderText("Pick one or more files…");

    await dropFile(
      user,
      new File(["q4 numbers"], DUPLICATE_TITLE, { type: "text/markdown" })
    );

    expect(screen.getByRole("alert")).toHaveTextContent(DUPLICATE_TITLE);
    expect(screen.getByRole("alert")).toHaveTextContent(/already in the knowledge store/i);
  });

  it("f25 does not warn when the uploaded name is new", async () => {
    const { user } = renderPicker();
    await screen.findByPlaceholderText("Pick one or more files…");

    await dropFile(
      user,
      new File(["fresh"], "Board_Minutes.md", { type: "text/markdown" })
    );

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("f25 attaches a freshly uploaded copy next to an attached copy with the same name", async () => {
    vi.spyOn(knowledgeStoreApi, "uploadDocumentsWithProgress").mockResolvedValue({
      ok: true,
      data: [{ filename: DUPLICATE_TITLE, doc_id: "d1e2f3a4b5c64d7e8f9a0b1c2d3e4f5a" }],
    });
    const { user, onChange } = renderPicker({
      attached: [{ doc_id: olderCopy.id, filename: DUPLICATE_TITLE }],
      inline: [],
    });
    await screen.findByPlaceholderText("Pick one or more files…");

    await dropFile(
      user,
      new File(["q4 numbers"], DUPLICATE_TITLE, { type: "text/markdown" })
    );
    await user.click(screen.getByRole("button", { name: /save to ks/i }));

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({
        attached: [
          { doc_id: olderCopy.id, filename: DUPLICATE_TITLE },
          { doc_id: "d1e2f3a4b5c64d7e8f9a0b1c2d3e4f5a", filename: DUPLICATE_TITLE },
        ],
        inline: [],
      })
    );
  });
});
