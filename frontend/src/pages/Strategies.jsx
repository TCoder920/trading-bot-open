import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import Tooltip from "../components/Tooltip";
import { get, post, patch, del } from "../api";

export default function Strategies() {
  const [strategies, setStrategies] = useState([]);
  const [active, setActive] = useState(null);
  const [templates, setTemplates] = useState({});
  const [showForm, setShowForm] = useState(false);
  const [editName, setEditName] = useState(null);
  const [form, setForm] = useState({ name: "", template: "", enabled: false, config: {} });
  const [error, setError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [s, t] = await Promise.all([get("/api/strategies"), get("/api/strategies/templates")]);
      setStrategies(s.strategies);
      setActive(s.active);
      setTemplates(t);
    } catch (e) {
      setLoadError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const selectTemplate = (key) => {
    const t = templates[key];
    setForm((f) => ({ ...f, template: key, config: { ...t?.default_config, ...f.config } }));
  };

  const save = async () => {
    setError(null);
    try {
      if (editName) {
        await patch(`/api/strategies/${editName}`, { template: form.template, enabled: form.enabled, config: form.config });
      } else {
        await post("/api/strategies", form);
      }
      setShowForm(false);
      setEditName(null);
      setForm({ name: "", template: "", enabled: false, config: {} });
      load();
    } catch (e) { setError(e.message); }
  };

  const startEdit = (s) => {
    setEditName(s.name);
    setForm({ name: s.name, template: s.template, enabled: s.enabled, config: { ...s.config } });
    setShowForm(true);
  };

  const remove = async (name) => {
    await del(`/api/strategies/${name}`);
    load();
  };

  const activate = async (name) => {
    await post(`/api/strategies/${name}/activate`);
    load();
  };

  const updateField = (key, val) => {
    setForm((f) => ({ ...f, config: { ...f.config, [key]: val } }));
  };

  return (
    <PageShell
      title="Strategies"
      description="Configure strategy templates, parameters, and activation."
      actions={
        <button className="btn" onClick={() => { setShowForm(true); setEditName(null); setForm({ name: "", template: "", enabled: false, config: {} }); }}>
          + New Strategy
        </button>
      }
    >

      {loading && <LoadingState />}
      {loadError && !loading && <ErrorState message={loadError} onRetry={load} />}

      {!loading && !loadError && showForm && (
        <div className="panel">
          <div className="section-title">{editName ? `Edit: ${editName}` : "New Strategy"}</div>
          {!editName && (
            <div className="form-group">
              <label className="form-label">Name</label>
              <input className="form-input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
            </div>
          )}
          <div className="form-group">
            <label className="form-label">Template <Tooltip text="Strategy type determines entry/exit logic." /></label>
            <select className="form-select" value={form.template} onChange={(e) => selectTemplate(e.target.value)}>
              <option value="">Select template...</option>
              {Object.entries(templates).map(([k, v]) => (
                <option key={k} value={k}>{v.label}</option>
              ))}
            </select>
            {form.template && templates[form.template] && (
              <div style={{ fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.25rem" }}>
                {templates[form.template].description}
              </div>
            )}
          </div>
          <div className="form-group">
            <label className="form-label">
              <input type="checkbox" checked={form.enabled} onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))} />
              Enabled
            </label>
          </div>
          {form.template && (
            <div className="section-title" style={{ marginTop: "1rem" }}>Parameters</div>
          )}
          <div className="form-row">
            {Object.entries(form.config).map(([k, v]) => (
              <div className="form-group" key={k}>
                <label className="form-label">
                  {k.replace(/_/g, " ")}
                  {templates[form.template]?.param_help?.[k] && (
                    <Tooltip text={templates[form.template].param_help[k]} />
                  )}
                </label>
                <input
                  className="form-input"
                  value={v}
                  onChange={(e) => {
                    const num = Number(e.target.value);
                    updateField(k, isNaN(num) || e.target.value === "" ? e.target.value : num);
                  }}
                />
              </div>
            ))}
          </div>
          {error && <div className="error-msg">{error}</div>}
          <div className="form-actions">
            <button className="btn" onClick={save}>{editName ? "Update" : "Create"}</button>
            <button className="btn" onClick={() => { setShowForm(false); setEditName(null); }}>Cancel</button>
          </div>
        </div>
      )}

      {!loading && !loadError && strategies.length === 0 && !showForm ? (
        <EmptyState message="No strategies configured. Create one to get started." />
      ) : !loading && !loadError && strategies.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Template</th>
                <th>Enabled</th>
                <th>Active</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => (
                <tr key={s.name}>
                  <td>{s.name}</td>
                  <td>{templates[s.template]?.label || s.template}</td>
                  <td><span className={`status-badge ${s.enabled ? "on" : "off"}`}>{s.enabled ? "Yes" : "No"}</span></td>
                  <td><span className={`status-badge ${s.is_active ? "on" : "off"}`}>{s.is_active ? "Active" : "—"}</span></td>
                  <td>
                    <div className="btn-row">
                      <button className="btn btn-sm" onClick={() => startEdit(s)}>Edit</button>
                      <button className="btn btn-sm" onClick={() => activate(s.name)}>Activate</button>
                      <button className="btn btn-sm" onClick={() => remove(s.name)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </PageShell>
  );
}
