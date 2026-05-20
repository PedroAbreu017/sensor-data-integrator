import { useState, useRef } from "react";
import axios from "axios";

const API_URL = "http://localhost:8000";

const TENANT_SEGMENTOS = {
  ORION: ["subsea"],
  NEXUS: ["substation"],
  ATLAS: ["subsea"],
};

export default function UploadPage() {
  const [tenant, setTenant] = useState("");
  const [segmento, setSegmento] = useState("");
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef();

  function handleTenantChange(t) {
    setTenant(t);
    const segs = TENANT_SEGMENTOS[t] || [];
    setSegmento(segs.length === 1 ? segs[0] : "");
  }

  function handleFile(f) {
    setFile(f);
    setJob(null);
    setError("");
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
  }

  async function handleUpload() {
    if (!tenant) return setError("Select a tenant.");
    if (!file) return setError("Select a file.");
    setError("");
    setLoading(true);
    setJob(null);

    try {
      const form = new FormData();
      form.append("tenant", tenant);
      form.append("file", file);

      const res = await axios.post(`${API_URL}/upload`, form);
      const jobId = res.data.job_id;

      let result = null;
      for (let i = 0; i < 120; i++) {
        await new Promise(r => setTimeout(r, 1000));
        const poll = await axios.get(`${API_URL}/jobs/${jobId}`);
        result = poll.data;
        if (result.status === "DONE" || result.status === "FAILED") break;
      }
      setJob(result);
    } catch (e) {
      setError(e.response?.data?.detail || "Error uploading file.");
    } finally {
      setLoading(false);
    }
  }

  const segmentos = TENANT_SEGMENTOS[tenant] || [];

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f5f5f3", fontFamily: "sans-serif" }}>
      <div style={{ background: "#fff", borderRadius: 16, padding: "2.5rem", width: 480, boxShadow: "0 2px 16px rgba(0,0,0,0.08)" }}>
        
        <p style={{ fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: "#999", margin: "0 0 4px" }}>
          Sensor Data Integrator
        </p>
        <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 1.5rem", color: "#111" }}>
          Upload Sensor Data
        </h1>

        <div style={{ marginBottom: "1.25rem" }}>
          <label style={{ display: "block", fontSize: 13, color: "#666", marginBottom: 6 }}>Tenant</label>
          <select
            value={tenant}
            onChange={e => handleTenantChange(e.target.value)}
            style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid #ddd", fontSize: 14 }}
          >
            <option value="">Select tenant...</option>
            {Object.keys(TENANT_SEGMENTOS).map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        <div style={{ marginBottom: "1.25rem" }}>
          <label style={{ display: "block", fontSize: 13, color: "#666", marginBottom: 6 }}>Segment</label>
          <select
            value={segmento}
            onChange={e => setSegmento(e.target.value)}
            disabled={!tenant}
            style={{ width: "100%", padding: "8px 12px", borderRadius: 8, border: "1px solid #ddd", fontSize: 14, background: !tenant ? "#f5f5f3" : "#fff", color: !tenant ? "#aaa" : "#111" }}
          >
            <option value="">Select segment...</option>
            {segmentos.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <div
          onDragOver={e => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current.click()}
          style={{ border: `2px dashed ${dragging ? "#333" : "#ccc"}`, borderRadius: 12, padding: "2rem", textAlign: "center", cursor: "pointer", background: dragging ? "#f9f9f9" : "#fafafa", transition: "all 0.15s" }}
        >
          <div style={{ fontSize: 28, marginBottom: 8 }}>↑</div>
          <p style={{ margin: "0 0 4px", fontSize: 14, fontWeight: 500 }}>Drag and drop file here</p>
          <p style={{ margin: "0 0 12px", fontSize: 12, color: "#999" }}>CSV, TXT or XLSX</p>
          <button style={{ fontSize: 13, padding: "6px 16px", borderRadius: 6, border: "1px solid #ccc", background: "#fff", cursor: "pointer" }}>
            Browse files
          </button>
          <input ref={inputRef} type="file" accept=".csv,.txt,.xlsx" style={{ display: "none" }} onChange={e => handleFile(e.target.files[0])} />
        </div>

        {file && (
          <div style={{ marginTop: 12, padding: "10px 14px", background: "#f5f5f3", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 13 }}>📄 {file.name} <span style={{ color: "#999" }}>({(file.size / 1024).toFixed(0)} KB)</span></span>
            <button onClick={e => { e.stopPropagation(); setFile(null); }} style={{ fontSize: 12, color: "#e55", background: "none", border: "none", cursor: "pointer" }}>Remove</button>
          </div>
        )}

        {error && <p style={{ marginTop: 12, fontSize: 13, color: "#e55" }}>{error}</p>}

        <button
          onClick={handleUpload}
          disabled={loading}
          style={{ width: "100%", marginTop: "1rem", padding: "10px", fontSize: 14, fontWeight: 500, borderRadius: 8, border: "none", background: loading ? "#ccc" : "#111", color: "#fff", cursor: loading ? "not-allowed" : "pointer" }}
        >
          {loading ? "Processing..." : "Upload"}
        </button>

        {job && (
          <div style={{ marginTop: "1.25rem", padding: "1rem", borderRadius: 10, background: job.result?.parts_uploaded > 0 ? "#f0faf4" : "#fff5f5", border: `1px solid ${job.result?.parts_uploaded > 0 ? "#b6e8c8" : "#ffc0c0"}` }}>
            <p style={{ margin: "0 0 6px", fontSize: 13, fontWeight: 500, color: job.result?.parts_uploaded > 0 ? "#1a7a40" : "#c0392b" }}>
              {job.result?.parts_uploaded > 0 ? "✓ Data successfully sent" : "✗ Processing failed"}
            </p>
            <p style={{ margin: "0 0 4px", fontSize: 12, color: "#666" }}>Records processed: <strong>{job.result?.records_processed ?? 0}</strong></p>
            <p style={{ margin: 0, fontSize: 12, color: "#666" }}>Parts uploaded: <strong>{job.result?.parts_uploaded ?? 0}</strong></p>
            {job.result?.errors?.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <p style={{ margin: "0 0 4px", fontSize: 12, color: "#999" }}>Validation warnings:</p>
                {job.result.errors.map((e, i) => (
                  <p key={i} style={{ margin: "2px 0", fontSize: 11, color: "#e55" }}>• {e.reason}</p>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}