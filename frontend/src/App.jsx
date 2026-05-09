import {
  Activity,
  Ban,
  Database,
  Download,
  Edit3,
  FileAudio,
  Headphones,
  ListChecks,
  Lock,
  LogOut,
  Network,
  PhoneCall,
  PhoneOutgoing,
  Play,
  RadioTower,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import SystemCheck from "./SystemCheck";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";
const APP_VERSION = import.meta.env.VITE_APP_VERSION || "V1.002";
const TOKEN_STORAGE_KEY = "sipcc_access_token";

const createEmptyTrunkForm = () => ({
  name: "",
  provider_name: "",
  description: "",
  host: "",
  port: 5060,
  transport: "udp",
  username: "",
  auth_username: "",
  sip_password: "",
  from_user: "",
  from_domain: "",
  outbound_proxy: "",
  caller_id: "",
  codecs: "ulaw,alaw",
  max_channels: 30,
  registration_enabled: false,
  enabled: true,
  status: "inactive",
});

const createEmptyWhitelistForm = () => ({
  sip_trunk_id: "",
  name: "",
  peer_cidr: "",
  description: "",
  enabled: true,
});

const createEmptyManualCallForm = () => ({
  sip_trunk_id: "",
  destination_number: "",
  caller_id: "",
});

const createEmptyBlacklistForm = () => ({
  phone_number: "",
  reason: "",
  enabled: true,
});

async function fetchJson(path, { token, ...options } = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const detail = typeof payload === "object" ? payload.detail : payload;
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join("; ") : detail || `HTTP ${response.status}`);
  }

  return payload;
}

async function fetchBlob(path, { token } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    const detail = typeof payload === "object" ? payload.detail : payload;
    throw new Error(detail || `HTTP ${response.status}`);
  }

  return response.blob();
}

function StatusPill({ label, tone = "neutral" }) {
  return <span className={`status-pill status-pill--${tone}`}>{label}</span>;
}

function Field({ label, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) || "");
  const [user, setUser] = useState(null);
  const [activeView, setActiveView] = useState("overview");
  const [ready, setReady] = useState(null);
  const [agents, setAgents] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const [calls, setCalls] = useState([]);
  const [sipTrunks, setSipTrunks] = useState([]);
  const [peerWhitelists, setPeerWhitelists] = useState([]);
  const [outboundCalls, setOutboundCalls] = useState([]);
  const [phoneBlacklists, setPhoneBlacklists] = useState([]);
  const [callRecordings, setCallRecordings] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [recordingAudioUrl, setRecordingAudioUrl] = useState("");
  const [selectedRecordingId, setSelectedRecordingId] = useState(null);
  const [loginForm, setLoginForm] = useState({ username: "admin", password: "" });
  const [trunkForm, setTrunkForm] = useState(createEmptyTrunkForm);
  const [whitelistForm, setWhitelistForm] = useState(createEmptyWhitelistForm);
  const [manualCallForm, setManualCallForm] = useState(createEmptyManualCallForm);
  const [blacklistForm, setBlacklistForm] = useState(createEmptyBlacklistForm);
  const [editingTrunkId, setEditingTrunkId] = useState(null);
  const [editingWhitelistId, setEditingWhitelistId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const stats = useMemo(
    () => [
      { label: "SIP 线路", value: sipTrunks.length, icon: Network },
      { label: "人工外呼", value: outboundCalls.length, icon: PhoneOutgoing },
      { label: "录音", value: callRecordings.length, icon: FileAudio },
      { label: "白名单", value: peerWhitelists.length, icon: ShieldCheck },
      { label: "黑名单", value: phoneBlacklists.length, icon: Ban },
      { label: "坐席", value: agents.length, icon: Headphones },
      { label: "审计日志", value: auditLogs.length, icon: ListChecks },
      { label: "数据库", value: ready?.database === "ok" ? "OK" : "--", icon: Database },
    ],
    [agents, auditLogs, callRecordings, outboundCalls, peerWhitelists, phoneBlacklists, ready, sipTrunks],
  );

  useEffect(() => {
    if (token) {
      refresh(token);
    }
  }, [token]);

  useEffect(() => {
    if (!token || !["overview", "manual", "recordings"].includes(activeView)) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      refresh(token, { silent: true });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [token, activeView]);

  function saveToken(nextToken) {
    setToken(nextToken);
    localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
  }

  function logout() {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken("");
    setUser(null);
    setError("");
  }

  async function login(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetchJson("/auth/login", {
        method: "POST",
        body: JSON.stringify(loginForm),
      });
      setUser(response.user);
      saveToken(response.access_token);
      await refresh(response.access_token);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function refresh(activeToken = token, options = {}) {
    if (!activeToken) {
      return;
    }

    const silent = Boolean(options.silent);
    if (!silent) {
      setLoading(true);
      setError("");
    }
    try {
      const [
        me,
        readyData,
        agentsData,
        campaignsData,
        callsData,
        trunkData,
        whitelistData,
        outboundCallData,
        blacklistData,
        recordingData,
        auditData,
      ] = await Promise.all([
        fetchJson("/auth/me", { token: activeToken }),
        fetchJson("/health/ready"),
        fetchJson("/agents"),
        fetchJson("/campaigns"),
        fetchJson("/calls"),
        fetchJson("/sip-trunks", { token: activeToken }),
        fetchJson("/sip-peer-whitelists", { token: activeToken }),
        fetchJson("/outbound-calls?limit=100", { token: activeToken }),
        fetchJson("/phone-blacklists", { token: activeToken }),
        fetchJson("/call-recordings?limit=100", { token: activeToken }),
        fetchJson("/audit-logs?limit=100", { token: activeToken }),
      ]);
      setUser(me);
      setReady(readyData);
      setAgents(agentsData);
      setCampaigns(campaignsData);
      setCalls(callsData);
      setSipTrunks(trunkData);
      setPeerWhitelists(whitelistData);
      setOutboundCalls(outboundCallData);
      setPhoneBlacklists(blacklistData);
      setCallRecordings(recordingData);
      setAuditLogs(auditData);
    } catch (err) {
      if (String(err.message).includes("Invalid bearer token") || String(err.message).includes("Missing bearer token")) {
        logout();
      }
      if (!silent) {
        setError(err.message);
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }

  async function seedDemo() {
    setLoading(true);
    setError("");
    try {
      await fetchJson("/agents", {
        method: "POST",
        token,
        body: JSON.stringify({
          extension: `60${Math.floor(10 + Math.random() * 89)}`,
          display_name: "外呼坐席",
          status: "available",
        }),
      });
      await fetchJson("/campaigns", {
        method: "POST",
        token,
        body: JSON.stringify({
          name: "测试外呼批次",
          description: "Docker Compose 启动后的示例批次",
          status: "active",
        }),
      });
      await fetchJson("/calls", {
        method: "POST",
        token,
        body: JSON.stringify({
          destination: "13800138000",
        }),
      });
      await refresh();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function saveTrunk(event) {
    event.preventDefault();
    const validationError = validateTrunkForm(trunkForm);
    if (validationError) {
      setError(validationError);
      return;
    }

    setLoading(true);
    setError("");
    try {
      const payload = serializeTrunkForm(trunkForm, Boolean(editingTrunkId));
      await fetchJson(editingTrunkId ? `/sip-trunks/${editingTrunkId}` : "/sip-trunks", {
        method: editingTrunkId ? "PATCH" : "POST",
        token,
        body: JSON.stringify(payload),
      });
      clearTrunkForm();
      await refresh();
      setActiveView("trunks");
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function deleteTrunk(id) {
    setLoading(true);
    setError("");
    try {
      await fetchJson(`/sip-trunks/${id}`, { method: "DELETE", token });
      await refresh();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  function startEditTrunk(trunk) {
    setEditingTrunkId(trunk.id);
    setTrunkForm({
      name: trunk.name || "",
      provider_name: trunk.provider_name || "",
      description: trunk.description || "",
      host: trunk.host || "",
      port: trunk.port || 5060,
      transport: trunk.transport || "udp",
      username: trunk.username || "",
      auth_username: trunk.auth_username || "",
      sip_password: "",
      from_user: trunk.from_user || "",
      from_domain: trunk.from_domain || "",
      outbound_proxy: trunk.outbound_proxy || "",
      caller_id: trunk.caller_id || "",
      codecs: (trunk.codecs || []).join(","),
      max_channels: trunk.max_channels || 30,
      registration_enabled: Boolean(trunk.registration_enabled),
      enabled: Boolean(trunk.enabled),
      status: trunk.status || "inactive",
    });
    setActiveView("trunks");
  }

  function clearTrunkForm() {
    setEditingTrunkId(null);
    setTrunkForm(createEmptyTrunkForm());
  }

  async function saveWhitelist(event) {
    event.preventDefault();
    if (!whitelistForm.name.trim() || !whitelistForm.peer_cidr.trim()) {
      setError("白名单名称和对端地址不能为空");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const payload = {
        ...whitelistForm,
        sip_trunk_id: whitelistForm.sip_trunk_id ? Number(whitelistForm.sip_trunk_id) : null,
      };
      await fetchJson(editingWhitelistId ? `/sip-peer-whitelists/${editingWhitelistId}` : "/sip-peer-whitelists", {
        method: editingWhitelistId ? "PATCH" : "POST",
        token,
        body: JSON.stringify(payload),
      });
      clearWhitelistForm();
      await refresh();
      setActiveView("whitelist");
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function deleteWhitelist(id) {
    setLoading(true);
    setError("");
    try {
      await fetchJson(`/sip-peer-whitelists/${id}`, { method: "DELETE", token });
      await refresh();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  function startEditWhitelist(item) {
    setEditingWhitelistId(item.id);
    setWhitelistForm({
      sip_trunk_id: item.sip_trunk_id || "",
      name: item.name || "",
      peer_cidr: item.peer_cidr || "",
      description: item.description || "",
      enabled: Boolean(item.enabled),
    });
    setActiveView("whitelist");
  }

  function clearWhitelistForm() {
    setEditingWhitelistId(null);
    setWhitelistForm(createEmptyWhitelistForm());
  }

  async function originateManualCall(event) {
    event.preventDefault();
    if (!manualCallForm.sip_trunk_id) {
      setError("请选择 SIP 线路");
      return;
    }
    if (!manualCallForm.destination_number.trim()) {
      setError("请输入被叫号码");
      return;
    }

    setLoading(true);
    setError("");
    try {
      await fetchJson("/outbound-calls", {
        method: "POST",
        token,
        body: JSON.stringify({
          sip_trunk_id: Number(manualCallForm.sip_trunk_id),
          destination_number: manualCallForm.destination_number,
          caller_id: manualCallForm.caller_id || null,
        }),
      });
      setManualCallForm(createEmptyManualCallForm());
      await refresh();
      setActiveView("manual");
    } catch (err) {
      setError(err.message);
      await refresh();
    } finally {
      setLoading(false);
    }
  }

  async function refreshOutboundCall(callId) {
    setLoading(true);
    setError("");
    try {
      await fetchJson(`/outbound-calls/${callId}/refresh`, { method: "POST", token });
      await refresh();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function hangupOutboundCall(callId) {
    setLoading(true);
    setError("");
    try {
      await fetchJson(`/outbound-calls/${callId}/hangup`, { method: "POST", token });
      await refresh();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function saveBlacklist(event) {
    event.preventDefault();
    if (!blacklistForm.phone_number.trim()) {
      setError("请输入黑名单号码");
      return;
    }

    setLoading(true);
    setError("");
    try {
      await fetchJson("/phone-blacklists", {
        method: "POST",
        token,
        body: JSON.stringify(blacklistForm),
      });
      setBlacklistForm(createEmptyBlacklistForm());
      await refresh();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function deleteBlacklist(entryId) {
    setLoading(true);
    setError("");
    try {
      await fetchJson(`/phone-blacklists/${entryId}`, { method: "DELETE", token });
      await refresh();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  async function playRecording(recording) {
    setLoading(true);
    setError("");
    try {
      const blob = await fetchBlob(`/call-recordings/${recording.id}/play`, { token });
      if (recordingAudioUrl) {
        URL.revokeObjectURL(recordingAudioUrl);
      }
      setRecordingAudioUrl(URL.createObjectURL(blob));
      setSelectedRecordingId(recording.id);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function downloadRecording(recording) {
    setLoading(true);
    setError("");
    try {
      const blob = await fetchBlob(`/call-recordings/${recording.id}/download`, { token });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = recording.filename || `recording-${recording.id}.wav`;
      anchor.click();
      URL.revokeObjectURL(url);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function deleteRecording(recordingId) {
    setLoading(true);
    setError("");
    try {
      await fetchJson(`/call-recordings/${recordingId}`, { method: "DELETE", token });
      if (selectedRecordingId === recordingId && recordingAudioUrl) {
        URL.revokeObjectURL(recordingAudioUrl);
        setRecordingAudioUrl("");
        setSelectedRecordingId(null);
      }
      await refresh();
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <main className="login-shell">
        <form className="login-panel" onSubmit={login}>
          <div className="brand brand--login">
            <RadioTower size={30} aria-hidden="true" />
            <div>
              <strong>SIP 外呼中心</strong>
              <span>线路与白名单管理 · {APP_VERSION}</span>
            </div>
          </div>
          <Field label="用户名">
            <input
              value={loginForm.username}
              onChange={(event) => setLoginForm((current) => ({ ...current, username: event.target.value }))}
              autoComplete="username"
              required
            />
          </Field>
          <Field label="密码">
            <input
              type="password"
              value={loginForm.password}
              onChange={(event) => setLoginForm((current) => ({ ...current, password: event.target.value }))}
              autoComplete="current-password"
              required
            />
          </Field>
          {error && <div className="error-banner">登录失败：{error}</div>}
          <button className="primary-button primary-button--wide" disabled={loading}>
            <Lock size={16} aria-hidden="true" />
            登录
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <RadioTower size={28} aria-hidden="true" />
          <div>
            <strong>SIP 外呼中心</strong>
            <span>
              {user?.username || "Authenticated"} · {APP_VERSION}
            </span>
          </div>
        </div>
        <nav className="nav-list" aria-label="主导航">
          <NavButton active={activeView === "overview"} onClick={() => setActiveView("overview")}>
            总览
          </NavButton>
          <NavButton active={activeView === "trunks"} onClick={() => setActiveView("trunks")}>
            SIP 线路
          </NavButton>
          <NavButton active={activeView === "manual"} onClick={() => setActiveView("manual")}>
            人工外呼
          </NavButton>
          <NavButton active={activeView === "recordings"} onClick={() => setActiveView("recordings")}>
            录音管理
          </NavButton>
          <NavButton active={activeView === "whitelist"} onClick={() => setActiveView("whitelist")}>
            对端白名单
          </NavButton>
          <NavButton active={activeView === "audit"} onClick={() => setActiveView("audit")}>
            审计日志
          </NavButton>
          <NavButton active={activeView === "system-check"} onClick={() => setActiveView("system-check")}>
            系统自检
          </NavButton>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Outbound Console</p>
            <h1>
              小型 SIP 外呼呼叫中心
              <span className="version-badge">{APP_VERSION}</span>
            </h1>
          </div>
          <div className="actions">
            <button className="icon-button" onClick={() => refresh()} disabled={loading} title="刷新">
              <RefreshCw size={18} aria-hidden="true" />
            </button>
            <button className="primary-button" onClick={seedDemo} disabled={loading}>
              写入演示数据
            </button>
            <button className="icon-button" onClick={logout} title="退出">
              <LogOut size={18} aria-hidden="true" />
            </button>
          </div>
        </header>

        {error && <div className="error-banner">请求失败：{error}</div>}

        {activeView === "overview" && renderOverview(stats, agents, campaigns, calls)}
        {activeView === "trunks" &&
          renderTrunks({
            sipTrunks,
            trunkForm,
            editingTrunkId,
            loading,
            setTrunkForm,
            saveTrunk,
            clearTrunkForm,
            startEditTrunk,
            deleteTrunk,
          })}
        {activeView === "manual" &&
          renderManualCalls({
            sipTrunks,
            outboundCalls,
            phoneBlacklists,
            manualCallForm,
            blacklistForm,
            loading,
            setManualCallForm,
            setBlacklistForm,
            originateManualCall,
            refreshOutboundCall,
            hangupOutboundCall,
            saveBlacklist,
            deleteBlacklist,
          })}
        {activeView === "recordings" &&
          renderRecordings({
            callRecordings,
            recordingAudioUrl,
            selectedRecordingId,
            loading,
            playRecording,
            downloadRecording,
            deleteRecording,
          })}
        {activeView === "whitelist" &&
          renderWhitelist({
            peerWhitelists,
            sipTrunks,
            whitelistForm,
            editingWhitelistId,
            loading,
            setWhitelistForm,
            saveWhitelist,
            clearWhitelistForm,
            startEditWhitelist,
            deleteWhitelist,
          })}
        {activeView === "audit" && renderAuditLogs(auditLogs)}
        {activeView === "system-check" && <SystemCheck apiBaseUrl={API_BASE_URL} token={token} />}
      </section>
    </main>
  );
}

function NavButton({ active, children, onClick }) {
  return (
    <button className={`nav-link ${active ? "nav-link--active" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

function renderOverview(stats, agents, campaigns, calls) {
  return (
    <>
      <section id="overview" className="stat-grid" aria-label="系统概览">
        {stats.map((item) => {
          const Icon = item.icon;
          return (
            <article className="stat-card" key={item.label}>
              <Icon size={20} aria-hidden="true" />
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </article>
          );
        })}
      </section>

      <section className="content-grid">
        <article id="agents" className="panel">
          <div className="panel-header">
            <h2>坐席</h2>
            <StatusPill label={`${agents.length} 个`} />
          </div>
          <div className="table">
            {agents.length === 0 ? (
              <p className="empty">暂无坐席</p>
            ) : (
              agents.map((agent) => (
                <div className="table-row table-row--agents" key={agent.id}>
                  <span>{agent.extension}</span>
                  <strong>{agent.display_name}</strong>
                  <StatusPill label={agent.status} tone={agent.status === "available" ? "success" : "neutral"} />
                </div>
              ))
            )}
          </div>
        </article>

        <article id="campaigns" className="panel">
          <div className="panel-header">
            <h2>外呼批次</h2>
            <StatusPill label={`${campaigns.length} 个`} />
          </div>
          <div className="table">
            {campaigns.length === 0 ? (
              <p className="empty">暂无批次</p>
            ) : (
              campaigns.map((campaign) => (
                <div className="table-row table-row--agents" key={campaign.id}>
                  <span>#{campaign.id}</span>
                  <strong>{campaign.name}</strong>
                  <StatusPill label={campaign.status} tone={campaign.status === "active" ? "success" : "neutral"} />
                </div>
              ))
            )}
          </div>
        </article>
      </section>

      <section id="calls" className="panel">
        <div className="panel-header">
          <h2>最近外呼</h2>
          <StatusPill label={`${calls.length} 条`} />
        </div>
        <div className="table table--wide">
          {calls.length === 0 ? (
            <p className="empty">暂无外呼记录</p>
          ) : (
            calls.map((call) => (
              <div className="table-row table-row--calls" key={call.id}>
                <span>#{call.id}</span>
                <strong>{call.destination}</strong>
                <span>{new Date(call.created_at).toLocaleString()}</span>
                <StatusPill label={call.status} tone={call.status === "queued" ? "warning" : "neutral"} />
              </div>
            ))
          )}
        </div>
      </section>
    </>
  );
}

function renderManualCalls(props) {
  const {
    sipTrunks,
    outboundCalls,
    phoneBlacklists,
    manualCallForm,
    blacklistForm,
    loading,
    setManualCallForm,
    setBlacklistForm,
    originateManualCall,
    refreshOutboundCall,
    hangupOutboundCall,
    saveBlacklist,
    deleteBlacklist,
  } = props;
  const enabledTrunks = sipTrunks.filter((trunk) => trunk.enabled);
  const trunkNameById = new Map(sipTrunks.map((item) => [item.id, item.name]));

  return (
    <>
      <section className="management-grid">
        <form className="panel form-panel" onSubmit={originateManualCall}>
          <div className="panel-header">
            <h2>发起人工外呼</h2>
            <StatusPill label="单次外呼" tone="success" />
          </div>
          <div className="form-grid">
            <Field label="SIP 线路">
              <select value={manualCallForm.sip_trunk_id} onChange={updateForm(setManualCallForm, "sip_trunk_id")} required>
                <option value="">请选择线路</option>
                {enabledTrunks.map((trunk) => (
                  <option value={trunk.id} key={trunk.id}>
                    {trunk.name} ({trunk.host})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="被叫号码">
              <input
                value={manualCallForm.destination_number}
                onChange={updateForm(setManualCallForm, "destination_number")}
                required
                maxLength={32}
                inputMode="tel"
                placeholder="13800138000"
              />
            </Field>
            <Field label="主叫号码">
              <input
                value={manualCallForm.caller_id}
                onChange={updateForm(setManualCallForm, "caller_id")}
                maxLength={80}
                inputMode="tel"
              />
            </Field>
          </div>
          <div className="form-actions">
            <button className="primary-button" disabled={loading || enabledTrunks.length === 0}>
              <PhoneOutgoing size={16} aria-hidden="true" />
              发起外呼
            </button>
            <button className="secondary-button" type="button" onClick={() => setManualCallForm(createEmptyManualCallForm())}>
              重置
            </button>
          </div>
        </form>

        <article className="panel">
          <div className="panel-header">
            <h2>外呼状态</h2>
            <StatusPill label={`${outboundCalls.length} 条`} />
          </div>
          <div className="table">
            {outboundCalls.length === 0 ? (
              <p className="empty">暂无人工外呼记录</p>
            ) : (
              outboundCalls.map((call) => (
                <div className="table-row table-row--outbound" key={call.id}>
                  <div>
                    <strong>{call.destination_number}</strong>
                    <span>{call.sip_trunk_id ? trunkNameById.get(call.sip_trunk_id) || `#${call.sip_trunk_id}` : "未知线路"}</span>
                  </div>
                  <StatusPill label={formatCallStatus(call.status)} tone={callStatusTone(call.status)} />
                  <span>{new Date(call.created_at).toLocaleString()}</span>
                  <div className="row-actions">
                    <button className="icon-button" type="button" onClick={() => refreshOutboundCall(call.id)} title="刷新状态">
                      <RefreshCw size={16} aria-hidden="true" />
                    </button>
                    {isActiveCall(call.status) && (
                      <button className="icon-button icon-button--danger" type="button" onClick={() => hangupOutboundCall(call.id)} title="挂断">
                        <PhoneCall size={16} aria-hidden="true" />
                      </button>
                    )}
                  </div>
                  {call.failure_reason && <p className="row-note">{call.failure_reason}</p>}
                  {call.hangup_cause && <p className="row-note">挂断原因：{call.hangup_cause}</p>}
                </div>
              ))
            )}
          </div>
        </article>
      </section>

      <section className="management-grid">
        <form className="panel form-panel" onSubmit={saveBlacklist}>
          <div className="panel-header">
            <h2>号码黑名单</h2>
            <StatusPill label="外呼前拦截" tone="warning" />
          </div>
          <div className="form-grid">
            <Field label="号码">
              <input
                value={blacklistForm.phone_number}
                onChange={updateForm(setBlacklistForm, "phone_number")}
                required
                maxLength={32}
                inputMode="tel"
              />
            </Field>
            <Field label="原因">
              <input value={blacklistForm.reason} onChange={updateForm(setBlacklistForm, "reason")} maxLength={160} />
            </Field>
          </div>
          <div className="switch-row">
            <label>
              <input type="checkbox" checked={blacklistForm.enabled} onChange={updateChecked(setBlacklistForm, "enabled")} />
              启用黑名单
            </label>
          </div>
          <div className="form-actions">
            <button className="primary-button" disabled={loading}>
              <Ban size={16} aria-hidden="true" />
              添加黑名单
            </button>
            <button className="secondary-button" type="button" onClick={() => setBlacklistForm(createEmptyBlacklistForm())}>
              重置
            </button>
          </div>
        </form>

        <article className="panel">
          <div className="panel-header">
            <h2>已拦截号码</h2>
            <StatusPill label={`${phoneBlacklists.length} 条`} />
          </div>
          <div className="table">
            {phoneBlacklists.length === 0 ? (
              <p className="empty">暂无黑名单</p>
            ) : (
              phoneBlacklists.map((item) => (
                <div className="table-row table-row--blacklist" key={item.id}>
                  <div>
                    <strong>{item.normalized_number}</strong>
                    <span>{item.reason || "未填写原因"}</span>
                  </div>
                  <StatusPill label={item.enabled ? "enabled" : "disabled"} tone={item.enabled ? "warning" : "neutral"} />
                  <button className="icon-button icon-button--danger" type="button" onClick={() => deleteBlacklist(item.id)} title="删除">
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </div>
              ))
            )}
          </div>
        </article>
      </section>
    </>
  );
}

function renderRecordings(props) {
  const {
    callRecordings,
    recordingAudioUrl,
    selectedRecordingId,
    loading,
    playRecording,
    downloadRecording,
    deleteRecording,
  } = props;

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>录音管理</h2>
        <StatusPill label={`${callRecordings.length} 条`} />
      </div>
      {recordingAudioUrl && (
        <div className="player-bar">
          <div>
            <strong>正在播放</strong>
            <span>录音 #{selectedRecordingId}</span>
          </div>
          <audio controls src={recordingAudioUrl} />
        </div>
      )}
      <div className="table">
        {callRecordings.length === 0 ? (
          <p className="empty">暂无录音</p>
        ) : (
          callRecordings.map((recording) => (
            <div className="table-row table-row--recordings" key={recording.id}>
              <div>
                <strong>{recording.destination_number}</strong>
                <span>{recording.filename}</span>
              </div>
              <StatusPill label={formatRecordingStatus(recording.status)} tone={recordingStatusTone(recording.status)} />
              <span>{formatBytes(recording.file_size_bytes)}</span>
              <span>{recording.retention_expires_at ? new Date(recording.retention_expires_at).toLocaleDateString() : "长期保留"}</span>
              <div className="row-actions">
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => playRecording(recording)}
                  title="播放"
                  disabled={loading || !isRecordingCompleted(recording.status)}
                >
                  <Play size={16} aria-hidden="true" />
                </button>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => downloadRecording(recording)}
                  title="下载"
                  disabled={loading || !isRecordingCompleted(recording.status)}
                >
                  <Download size={16} aria-hidden="true" />
                </button>
                <button className="icon-button icon-button--danger" type="button" onClick={() => deleteRecording(recording.id)} title="删除">
                  <Trash2 size={16} aria-hidden="true" />
                </button>
              </div>
              {isRecordingCompleted(recording.status) && selectedRecordingId === recording.id && recordingAudioUrl && (
                <audio className="row-audio" controls src={recordingAudioUrl} />
              )}
              {!isRecordingCompleted(recording.status) && <p className="row-note">录音处理中，请稍后刷新</p>}
              {recording.failure_reason && <p className="row-note">{recording.failure_reason}</p>}
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function renderTrunks(props) {
  const {
    sipTrunks,
    trunkForm,
    editingTrunkId,
    loading,
    setTrunkForm,
    saveTrunk,
    clearTrunkForm,
    startEditTrunk,
    deleteTrunk,
  } = props;

  return (
    <section className="management-grid">
      <form className="panel form-panel" onSubmit={saveTrunk}>
        <div className="panel-header">
          <h2>{editingTrunkId ? "编辑 SIP 线路" : "新增 SIP 线路"}</h2>
          {editingTrunkId && (
            <button className="icon-button" type="button" onClick={clearTrunkForm} title="取消编辑">
              <X size={18} aria-hidden="true" />
            </button>
          )}
        </div>
        <div className="form-grid">
          <Field label="线路名称">
            <input value={trunkForm.name} onChange={updateForm(setTrunkForm, "name")} required maxLength={120} />
          </Field>
          <Field label="运营商">
            <input value={trunkForm.provider_name} onChange={updateForm(setTrunkForm, "provider_name")} maxLength={120} />
          </Field>
          <Field label="SIP 主机">
            <input value={trunkForm.host} onChange={updateForm(setTrunkForm, "host")} required maxLength={255} />
          </Field>
          <Field label="端口">
            <input type="number" value={trunkForm.port} onChange={updateForm(setTrunkForm, "port")} min="1" max="65535" required />
          </Field>
          <Field label="传输协议">
            <select value={trunkForm.transport} onChange={updateForm(setTrunkForm, "transport")}>
              <option value="udp">UDP</option>
              <option value="tcp">TCP</option>
              <option value="tls">TLS</option>
            </select>
          </Field>
          <Field label="状态">
            <select value={trunkForm.status} onChange={updateForm(setTrunkForm, "status")}>
              <option value="inactive">Inactive</option>
              <option value="active">Active</option>
              <option value="error">Error</option>
              <option value="disabled">Disabled</option>
            </select>
          </Field>
          <Field label="SIP 用户名">
            <input value={trunkForm.username} onChange={updateForm(setTrunkForm, "username")} maxLength={120} />
          </Field>
          <Field label="认证用户名">
            <input value={trunkForm.auth_username} onChange={updateForm(setTrunkForm, "auth_username")} maxLength={120} />
          </Field>
          <Field label="SIP 密码">
            <input
              type="password"
              value={trunkForm.sip_password}
              onChange={updateForm(setTrunkForm, "sip_password")}
              maxLength={256}
              autoComplete="new-password"
              placeholder={editingTrunkId ? "留空则不变" : ""}
            />
          </Field>
          <Field label="主叫号码">
            <input value={trunkForm.caller_id} onChange={updateForm(setTrunkForm, "caller_id")} maxLength={80} />
          </Field>
          <Field label="From User">
            <input value={trunkForm.from_user} onChange={updateForm(setTrunkForm, "from_user")} maxLength={120} />
          </Field>
          <Field label="From Domain">
            <input value={trunkForm.from_domain} onChange={updateForm(setTrunkForm, "from_domain")} maxLength={255} />
          </Field>
          <Field label="Outbound Proxy">
            <input value={trunkForm.outbound_proxy} onChange={updateForm(setTrunkForm, "outbound_proxy")} maxLength={255} />
          </Field>
          <Field label="Codecs">
            <input value={trunkForm.codecs} onChange={updateForm(setTrunkForm, "codecs")} required />
          </Field>
          <Field label="最大并发">
            <input type="number" value={trunkForm.max_channels} onChange={updateForm(setTrunkForm, "max_channels")} min="1" max="10000" />
          </Field>
          <Field label="描述">
            <textarea value={trunkForm.description} onChange={updateForm(setTrunkForm, "description")} rows={3} />
          </Field>
        </div>
        <div className="switch-row">
          <label>
            <input type="checkbox" checked={trunkForm.registration_enabled} onChange={updateChecked(setTrunkForm, "registration_enabled")} />
            注册到运营商
          </label>
          <label>
            <input type="checkbox" checked={trunkForm.enabled} onChange={updateChecked(setTrunkForm, "enabled")} />
            启用线路
          </label>
        </div>
        <div className="form-actions">
          <button className="primary-button" disabled={loading}>
            <Save size={16} aria-hidden="true" />
            保存线路
          </button>
          <button className="secondary-button" type="button" onClick={clearTrunkForm}>
            重置
          </button>
        </div>
      </form>

      <article className="panel">
        <div className="panel-header">
          <h2>SIP 线路</h2>
          <StatusPill label={`${sipTrunks.length} 条`} />
        </div>
        <div className="table">
          {sipTrunks.length === 0 ? (
            <p className="empty">暂无 SIP 线路</p>
          ) : (
            sipTrunks.map((trunk) => (
              <div className="table-row table-row--trunks" key={trunk.id}>
                <div>
                  <strong>{trunk.name}</strong>
                  <span>{trunk.host}:{trunk.port}</span>
                </div>
                <StatusPill label={trunk.transport.toUpperCase()} />
                <StatusPill label={formatTrunkStatus(trunk.status)} tone={trunk.status === "active" ? "success" : trunk.status === "error" ? "danger" : "warning"} />
                <StatusPill label={`并发 ${trunk.max_channels || 1}`} />
                <StatusPill label={trunk.enabled ? "enabled" : "disabled"} tone={trunk.enabled ? "success" : "neutral"} />
                <StatusPill label={trunk.password_configured ? "密码已配置" : "无密码"} tone={trunk.password_configured ? "success" : "warning"} />
                <div className="row-actions">
                  <button className="icon-button" type="button" onClick={() => startEditTrunk(trunk)} title="编辑">
                    <Edit3 size={16} aria-hidden="true" />
                  </button>
                  <button className="icon-button icon-button--danger" type="button" onClick={() => deleteTrunk(trunk.id)} title="删除">
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </article>
    </section>
  );
}

function renderWhitelist(props) {
  const {
    peerWhitelists,
    sipTrunks,
    whitelistForm,
    editingWhitelistId,
    loading,
    setWhitelistForm,
    saveWhitelist,
    clearWhitelistForm,
    startEditWhitelist,
    deleteWhitelist,
  } = props;

  const trunkNameById = new Map(sipTrunks.map((item) => [item.id, item.name]));

  return (
    <section className="management-grid">
      <form className="panel form-panel" onSubmit={saveWhitelist}>
        <div className="panel-header">
          <h2>{editingWhitelistId ? "编辑对端白名单" : "新增对端白名单"}</h2>
          {editingWhitelistId && (
            <button className="icon-button" type="button" onClick={clearWhitelistForm} title="取消编辑">
              <X size={18} aria-hidden="true" />
            </button>
          )}
        </div>
        <div className="form-grid">
          <Field label="所属线路">
            <select value={whitelistForm.sip_trunk_id} onChange={updateForm(setWhitelistForm, "sip_trunk_id")}>
              <option value="">全局</option>
              {sipTrunks.map((trunk) => (
                <option value={trunk.id} key={trunk.id}>
                  {trunk.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="名称">
            <input value={whitelistForm.name} onChange={updateForm(setWhitelistForm, "name")} required maxLength={120} />
          </Field>
          <Field label="对端 IP/CIDR">
            <input value={whitelistForm.peer_cidr} onChange={updateForm(setWhitelistForm, "peer_cidr")} required maxLength={64} />
          </Field>
          <Field label="描述">
            <textarea value={whitelistForm.description} onChange={updateForm(setWhitelistForm, "description")} rows={3} />
          </Field>
        </div>
        <div className="switch-row">
          <label>
            <input type="checkbox" checked={whitelistForm.enabled} onChange={updateChecked(setWhitelistForm, "enabled")} />
            启用白名单
          </label>
        </div>
        <div className="form-actions">
          <button className="primary-button" disabled={loading}>
            <Save size={16} aria-hidden="true" />
            保存白名单
          </button>
          <button className="secondary-button" type="button" onClick={clearWhitelistForm}>
            重置
          </button>
        </div>
      </form>

      <article className="panel">
        <div className="panel-header">
          <h2>对端白名单</h2>
          <StatusPill label={`${peerWhitelists.length} 条`} />
        </div>
        <div className="table">
          {peerWhitelists.length === 0 ? (
            <p className="empty">暂无白名单</p>
          ) : (
            peerWhitelists.map((item) => (
              <div className="table-row table-row--whitelist" key={item.id}>
                <div>
                  <strong>{item.name}</strong>
                  <span>{item.peer_cidr}</span>
                </div>
                <span>{item.sip_trunk_id ? trunkNameById.get(item.sip_trunk_id) || `#${item.sip_trunk_id}` : "全局"}</span>
                <StatusPill label={item.enabled ? "enabled" : "disabled"} tone={item.enabled ? "success" : "neutral"} />
                <div className="row-actions">
                  <button className="icon-button" type="button" onClick={() => startEditWhitelist(item)} title="编辑">
                    <Edit3 size={16} aria-hidden="true" />
                  </button>
                  <button className="icon-button icon-button--danger" type="button" onClick={() => deleteWhitelist(item.id)} title="删除">
                    <Trash2 size={16} aria-hidden="true" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </article>
    </section>
  );
}

function renderAuditLogs(auditLogs) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>审计日志</h2>
        <StatusPill label={`${auditLogs.length} 条`} />
      </div>
      <div className="table">
        {auditLogs.length === 0 ? (
          <p className="empty">暂无审计日志</p>
        ) : (
          auditLogs.map((item) => (
            <div className="audit-row" key={item.id}>
              <div className="audit-main">
                <strong>{item.action}</strong>
                <span>
                  {item.resource_type}
                  {item.resource_id ? ` #${item.resource_id}` : ""} · {item.username || "system"} · {new Date(item.created_at).toLocaleString()}
                </span>
              </div>
              <code>{JSON.stringify(item.after_values || item.before_values || {})}</code>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function updateForm(setter, key) {
  return (event) => {
    const value = event.target.type === "number" ? Number(event.target.value) : event.target.value;
    setter((current) => ({ ...current, [key]: value }));
  };
}

function updateChecked(setter, key) {
  return (event) => {
    setter((current) => ({ ...current, [key]: event.target.checked }));
  };
}

function serializeTrunkForm(form, isEdit) {
  const payload = {
    ...form,
    port: Number(form.port),
    max_channels: Number(form.max_channels),
    codecs: form.codecs
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  };

  if (isEdit && !payload.sip_password) {
    delete payload.sip_password;
  }

  return payload;
}

function validateTrunkForm(form) {
  if (!form.name.trim()) {
    return "线路名称不能为空";
  }
  if (!form.host.trim()) {
    return "SIP 主机不能为空";
  }
  if (Number(form.port) < 1 || Number(form.port) > 65535) {
    return "端口必须在 1 到 65535 之间";
  }
  if (!form.codecs.split(",").map((item) => item.trim()).filter(Boolean).length) {
    return "至少需要一个 codec";
  }
  if (Number(form.max_channels) < 1) {
    return "最大并发必须大于 0";
  }
  return "";
}

function isActiveCall(status) {
  return ["queued", "initiating", "dialing", "ringing", "answered", "in_progress", "hangup_requested"].includes(status);
}

function callStatusTone(status) {
  if (status === "answered" || status === "in_progress") {
    return "success";
  }
  if (status === "failed" || status === "blocked" || status === "rate_limited") {
    return "danger";
  }
  if (status === "initiating" || status === "dialing" || status === "ringing" || status === "hangup_requested") {
    return "warning";
  }
  return "neutral";
}

function formatCallStatus(status) {
  const labels = {
    queued: "排队中",
    initiating: "呼叫中",
    dialing: "呼叫中",
    ringing: "呼叫中",
    answered: "已接通",
    in_progress: "已接通",
    hangup_requested: "挂断中",
    ended: "已结束",
    completed: "已挂机",
    hangup: "已挂机",
    failed: "失败",
    blocked: "黑名单拦截",
    rate_limited: "频率限制",
  };
  return labels[status] || status;
}

function recordingStatusTone(status) {
  if (isRecordingCompleted(status)) {
    return "success";
  }
  if (status === "pending" || status === "recording") {
    return "warning";
  }
  if (status === "failed" || status === "deleted" || status === "expired") {
    return "danger";
  }
  return "neutral";
}

function formatRecordingStatus(status) {
  const labels = {
    pending: "等待录音",
    recording: "录音中",
    completed: "已完成",
    available: "已完成",
    failed: "失败",
    deleted: "已删除",
    expired: "已过期",
  };
  return labels[status] || status;
}

function isRecordingCompleted(status) {
  return status === "completed" || status === "available";
}

function formatTrunkStatus(status) {
  const labels = {
    active: "线路正常",
    inactive: "待探测",
    error: "线路异常",
    disabled: "已禁用",
  };
  return labels[status] || status;
}

function formatBytes(value) {
  if (!value) {
    return "--";
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export default App;
