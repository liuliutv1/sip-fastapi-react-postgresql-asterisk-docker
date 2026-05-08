import { useMemo, useState } from "react";

type CheckStatus = "ok" | "warn" | "fail";

type SystemCheckResult = {
  item: string;
  status: CheckStatus;
  msg?: string;
};

type SystemCheckProps = {
  apiBaseUrl?: string;
  token?: string;
};

const statusIconMap: Record<CheckStatus, string> = {
  ok: "✅",
  warn: "⚠️",
  fail: "❌",
};

const statusLabelMap: Record<CheckStatus, string> = {
  ok: "正常",
  warn: "警告",
  fail: "失败",
};

function normalizeApiBaseUrl(value: string) {
  return value.replace(/\/+$/, "");
}

function normalizeResults(payload: unknown): SystemCheckResult[] {
  if (!Array.isArray(payload)) {
    throw new Error("接口返回格式不正确，预期为检测结果数组");
  }

  return payload.map((row, index) => {
    if (!row || typeof row !== "object") {
      return {
        item: `检测项 ${index + 1}`,
        status: "fail",
        msg: "接口返回了无法识别的检测项",
      };
    }

    const item = "item" in row && typeof row.item === "string" ? row.item : `检测项 ${index + 1}`;
    const status = "status" in row && typeof row.status === "string" ? row.status : "fail";
    const msg = "msg" in row && typeof row.msg === "string" ? row.msg : "";

    return {
      item,
      status: status === "ok" || status === "warn" || status === "fail" ? status : "fail",
      msg: msg || (status === "ok" ? "正常" : "未返回具体问题说明"),
    };
  });
}

export default function SystemCheck({ apiBaseUrl = "/api", token = "" }: SystemCheckProps) {
  const [results, setResults] = useState<SystemCheckResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastCheckedAt, setLastCheckedAt] = useState("");

  const summary = useMemo(() => {
    return results.reduce(
      (current, item) => ({
        ok: current.ok + (item.status === "ok" ? 1 : 0),
        warn: current.warn + (item.status === "warn" ? 1 : 0),
        fail: current.fail + (item.status === "fail" ? 1 : 0),
      }),
      { ok: 0, warn: 0, fail: 0 },
    );
  }, [results]);

  async function startCheck() {
    setLoading(true);
    setResults([]);

    try {
      const response = await fetch(`${normalizeApiBaseUrl(apiBaseUrl)}/system/check`, {
        headers: {
          Accept: "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });

      const payload = await response.json().catch(() => null);

      if (!response.ok) {
        const detail = payload && typeof payload === "object" && "detail" in payload ? String(payload.detail) : "";
        throw new Error(detail || `系统自检接口请求失败，状态码 ${response.status}`);
      }

      setResults(normalizeResults(payload));
      setLastCheckedAt(new Date().toLocaleString());
    } catch (error) {
      setResults([
        {
          item: "系统自检接口",
          status: "fail",
          msg: error instanceof Error ? error.message : "请求失败，请检查后端服务或网络连接",
        },
      ]);
      setLastCheckedAt(new Date().toLocaleString());
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="system-check panel">
      <div className="panel-header system-check__header">
        <div>
          <h2>系统自检</h2>
          <p>检测 SIP 端口、RTP 端口、Asterisk 服务和线路连通状态。</p>
        </div>
        <button className="primary-button" type="button" onClick={startCheck} disabled={loading}>
          {loading ? "检测中..." : "开始检测"}
        </button>
      </div>

      {results.length > 0 && (
        <div className="system-check__summary" aria-label="检测结果汇总">
          <span>正常 {summary.ok}</span>
          <span>警告 {summary.warn}</span>
          <span>失败 {summary.fail}</span>
          {lastCheckedAt && <time>最近检测：{lastCheckedAt}</time>}
        </div>
      )}

      <div className="system-check__results" aria-live="polite">
        {results.length === 0 ? (
          <p className="empty">{loading ? "正在检测系统配置，请稍候..." : "点击“开始检测”后，这里会显示每一项检测结果。"}</p>
        ) : (
          results.map((result, index) => (
            <article className={`system-check__item system-check__item--${result.status}`} key={`${result.item}-${index}`}>
              <span className="system-check__icon" aria-hidden="true">
                {statusIconMap[result.status]}
              </span>
              <div>
                <div className="system-check__title">
                  <strong>{result.item}</strong>
                  <span>{statusLabelMap[result.status]}</span>
                </div>
                <p>{result.status === "ok" ? result.msg || "正常" : result.msg || "请查看后端检测详情"}</p>
              </div>
            </article>
          ))
        )}
      </div>
    </section>
  );
}
