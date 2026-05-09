import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import SystemCheck from "../src/SystemCheck";

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe("SystemCheck", () => {
  it("calls backend and renders ok warn fail results", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { item: "SIP 信令端口", status: "ok", msg: "端口 5060 已开放" },
        { item: "RTP 端口范围", status: "warn", msg: "部分端口未开放" },
        { item: "Asterisk 服务状态", status: "fail", msg: "Asterisk 未运行" },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SystemCheck apiBaseUrl="/api" token="token-1" />);
    await userEvent.click(screen.getByRole("button", { name: "开始检测" }));

    await waitFor(() => {
      expect(screen.getByText("SIP 信令端口")).toBeInTheDocument();
      expect(screen.getByText("RTP 端口范围")).toBeInTheDocument();
      expect(screen.getByText("Asterisk 服务状态")).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith("/api/system/check", expect.objectContaining({
      headers: expect.objectContaining({ Authorization: "Bearer token-1" }),
    }));
    expect(screen.getByText("正常 1")).toBeInTheDocument();
    expect(screen.getByText("警告 1")).toBeInTheDocument();
    expect(screen.getByText("失败 1")).toBeInTheDocument();
  });

  it("renders backend error details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => ({ detail: "系统自检接口请求失败" }),
      }),
    );

    render(<SystemCheck apiBaseUrl="/api" token="token-1" />);
    await userEvent.click(screen.getByRole("button", { name: "开始检测" }));

    await waitFor(() => {
      expect(screen.getByText("系统自检接口")).toBeInTheDocument();
      expect(screen.getByText("系统自检接口请求失败")).toBeInTheDocument();
    });
  });
});
