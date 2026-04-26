import { useEffect, useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { API_BASE } from "@/lib/api";

interface Doctor {
  id: number;
  username: string;
  full_name: string;
}

interface Session {
  id: number;
  patient_id: number;
  doctor_id: number;
  path: string[];
  summary: string;
  created_at: string;
}

interface Patient {
  id: number;
  first_name: string;
  last_name: string;
  age: number | null;
  room_number: string | null;
  diagnosis: string | null;
  notes: string | null;
  session_count: number;
  last_session: string | null;
}

interface Props {
  token: string;
  doctor: Doctor;
  onStartSession: (patientId: number) => void;
  onLogout: () => void;
}

const API = "http://localhost:8000";

function authHeaders(token: string) {
  return { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
}

function formatDate(iso: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ro-RO", {
    day: "2-digit", month: "short", year: "numeric",
  });
}

const emptyForm = {
  first_name: "", last_name: "", age: "", room_number: "", diagnosis: "", notes: "",
};

export default function Dashboard({ token, doctor, onStartSession, onLogout }: Props) {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [loadingPatients, setLoadingPatients] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<Record<number, Session[]>>({});
  const [loadingSessions, setLoadingSessions] = useState<Record<number, boolean>>({});
  const [showAddForm, setShowAddForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [downloadingReport, setDownloadingReport] = useState<Record<number, boolean>>({});

  const fetchPatients = async () => {
    try {
      const res = await fetch(`${API}/api/patients`, {
        headers: authHeaders(token),
        credentials: "include",
      });
      if (res.ok) setPatients(await res.json());
    } finally {
      setLoadingPatients(false);
    }
  };

  useEffect(() => { fetchPatients(); }, []);

  const toggleHistory = async (patientId: number) => {
    if (expandedId === patientId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(patientId);
    if (sessions[patientId]) return;

    setLoadingSessions((prev) => ({ ...prev, [patientId]: true }));
    try {
      const res = await fetch(`${API}/api/patients/${patientId}/sessions`, {
        headers: authHeaders(token),
        credentials: "include",
      });
      if (res.ok) {
        const data: Session[] = await res.json();
        setSessions((prev) => ({ ...prev, [patientId]: data }));
      }
    } finally {
      setLoadingSessions((prev) => ({ ...prev, [patientId]: false }));
    }
  };

  const handleDelete = async (patientId: number, name: string) => {
    if (!confirm(`Delete patient ${name} and all their sessions? This cannot be undone.`)) return;
    const res = await fetch(`${API}/api/patients/${patientId}`, {
      method: "DELETE",
      headers: authHeaders(token),
      credentials: "include",
    });
    if (res.ok) {
      setPatients((prev) => prev.filter((p) => p.id !== patientId));
      if (expandedId === patientId) setExpandedId(null);
    }
  };

  const handleAddPatient = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    if (!form.first_name.trim() || !form.last_name.trim()) {
      setFormError("First name and last name are required.");
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/patients`, {
        method: "POST",
        headers: authHeaders(token),
        credentials: "include",
        body: JSON.stringify({
          first_name: form.first_name.trim(),
          last_name: form.last_name.trim(),
          age: form.age ? parseInt(form.age) : null,
          room_number: form.room_number.trim() || null,
          diagnosis: form.diagnosis.trim() || null,
          notes: form.notes.trim() || null,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setFormError(d.detail ?? "Failed to create patient.");
        return;
      }
      const created: Patient = await res.json();
      setPatients((prev) => [...prev, { ...created, session_count: 0, last_session: null }]);
      setShowAddForm(false);
      setForm(emptyForm);
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    await fetch(`${API}/auth/logout`, {
      method: "POST",
      headers: authHeaders(token),
      credentials: "include",
    }).catch(() => {});
    onLogout();
  };

  const handleDownloadReport = async (patientId: number, firstName: string, lastName: string) => {
    setDownloadingReport((prev) => ({ ...prev, [patientId]: true }));
    try {
      const res = await fetch(`${API_BASE}/api/patients/${patientId}/report`, {
        headers: { Authorization: `Bearer ${token}` },
        credentials: "include",
      });
      if (!res.ok) {
        alert("Failed to generate report. Please try again.");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `report_${firstName}_${lastName}_${new Date().toISOString().slice(0, 10)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Could not download report. Is the backend running?");
    } finally {
      setDownloadingReport((prev) => ({ ...prev, [patientId]: false }));
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white">
      {/* Top bar */}
      <header className="bg-slate-900 border-b border-slate-800 px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">SpeakWithMe</h1>
          <p className="text-slate-400 text-xs">Medical Communication System</p>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-slate-300 text-sm">{doctor.full_name}</span>
          <Button
            onClick={handleLogout}
            variant="outline"
            className="border-slate-700 text-slate-300 hover:bg-slate-800 hover:text-white text-sm h-8"
          >
            Logout
          </Button>
        </div>
      </header>

      {/* Main content */}
      <main className="max-w-5xl mx-auto px-6 py-8">
        {/* Section header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-lg font-semibold text-white">Your Patients</h2>
            <p className="text-slate-500 text-sm">{patients.length} patient{patients.length !== 1 ? "s" : ""}</p>
          </div>
          <Button
            onClick={() => { setShowAddForm(true); setFormError(""); setForm(emptyForm); }}
            className="bg-blue-600 hover:bg-blue-500 text-white text-sm h-9"
          >
            + Add Patient
          </Button>
        </div>

        {/* Patient list */}
        {loadingPatients ? (
          <p className="text-slate-500 text-center py-16">Loading patients…</p>
        ) : patients.length === 0 ? (
          <div className="text-center py-16 text-slate-500">
            <p className="text-lg">No patients yet.</p>
            <p className="text-sm mt-1">Click "Add Patient" to get started.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {patients.map((p) => (
              <div key={p.id} className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                {/* Card row */}
                <div className="p-5 flex items-start gap-4">
                  {/* Avatar */}
                  <div className="w-11 h-11 rounded-full bg-slate-700 flex items-center justify-center text-slate-300 font-semibold text-sm flex-shrink-0">
                    {p.first_name[0]}{p.last_name[0]}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-white">
                        {p.first_name} {p.last_name}
                      </h3>
                      {p.room_number && (
                        <span className="text-xs bg-slate-800 text-slate-400 px-2 py-0.5 rounded">
                          Room {p.room_number}
                        </span>
                      )}
                      {p.age && (
                        <span className="text-xs text-slate-500">{p.age} yrs</span>
                      )}
                    </div>
                    {p.diagnosis && (
                      <p className="text-slate-400 text-sm mt-0.5 truncate max-w-lg">
                        {p.diagnosis.length > 70 ? p.diagnosis.slice(0, 70) + "…" : p.diagnosis}
                      </p>
                    )}
                    <p className="text-slate-600 text-xs mt-1">
                      {p.session_count} session{p.session_count !== 1 ? "s" : ""}
                      {p.last_session ? ` · Last: ${formatDate(p.last_session)}` : ""}
                    </p>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Button
                      onClick={() => onStartSession(p.id)}
                      className="bg-green-600 hover:bg-green-500 text-white text-sm h-9 px-4"
                    >
                      Start Session
                    </Button>
                    <Button
                      onClick={() => toggleHistory(p.id)}
                      variant="outline"
                      className="border-slate-700 text-slate-300 hover:bg-slate-800 text-sm h-9 px-3"
                    >
                      {expandedId === p.id ? "Hide History" : "View History"}
                    </Button>
                    <Button
                      onClick={() => handleDownloadReport(p.id, p.first_name, p.last_name)}
                      disabled={downloadingReport[p.id]}
                      variant="outline"
                      className="border-slate-700 text-slate-300 hover:bg-slate-800 text-sm h-9 px-3"
                    >
                      {downloadingReport[p.id] ? "Generating…" : "Report"}
                    </Button>
                    <Button
                      onClick={() => handleDelete(p.id, `${p.first_name} ${p.last_name}`)}
                      variant="outline"
                      className="border-red-900 text-red-400 hover:bg-red-950 hover:text-red-300 text-sm h-9 px-3"
                    >
                      Delete
                    </Button>
                  </div>
                </div>

                {/* Session history panel */}
                {expandedId === p.id && (
                  <div className="border-t border-slate-800 bg-slate-950/50 px-5 py-4">
                    <h4 className="text-sm font-medium text-slate-400 mb-3">Session History</h4>
                    {loadingSessions[p.id] ? (
                      <p className="text-slate-600 text-sm">Loading…</p>
                    ) : !sessions[p.id] || sessions[p.id].length === 0 ? (
                      <p className="text-slate-600 text-sm">No sessions recorded yet.</p>
                    ) : (
                      <div className="space-y-3">
                        {sessions[p.id].map((s) => (
                          <div key={s.id} className="bg-slate-900 border border-slate-800 rounded-lg p-3">
                            <div className="flex items-center justify-between mb-1.5">
                              <span className="text-xs text-slate-500">{formatDate(s.created_at)}</span>
                              <span className="text-xs text-slate-600 font-mono">
                                {s.path.join(" → ")}
                              </span>
                            </div>
                            <p className="text-slate-300 text-sm leading-snug">{s.summary}</p>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Add Patient modal */}
      {showAddForm && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl w-full max-w-md shadow-2xl">
            <div className="px-6 pt-6 pb-2">
              <h3 className="text-lg font-semibold text-white">Add New Patient</h3>
            </div>
            <form onSubmit={handleAddPatient} className="px-6 pb-6 space-y-4 mt-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-slate-300 text-sm">First Name *</Label>
                  <Input
                    value={form.first_name}
                    onChange={(e) => setForm({ ...form, first_name: e.target.value })}
                    className="bg-slate-800 border-slate-700 text-white"
                    placeholder="Ion"
                    required
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-slate-300 text-sm">Last Name *</Label>
                  <Input
                    value={form.last_name}
                    onChange={(e) => setForm({ ...form, last_name: e.target.value })}
                    className="bg-slate-800 border-slate-700 text-white"
                    placeholder="Popescu"
                    required
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-slate-300 text-sm">Age</Label>
                  <Input
                    type="number"
                    min={0}
                    max={150}
                    value={form.age}
                    onChange={(e) => setForm({ ...form, age: e.target.value })}
                    className="bg-slate-800 border-slate-700 text-white"
                    placeholder="65"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-slate-300 text-sm">Room Number</Label>
                  <Input
                    value={form.room_number}
                    onChange={(e) => setForm({ ...form, room_number: e.target.value })}
                    className="bg-slate-800 border-slate-700 text-white"
                    placeholder="A12"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label className="text-slate-300 text-sm">Diagnosis</Label>
                <Input
                  value={form.diagnosis}
                  onChange={(e) => setForm({ ...form, diagnosis: e.target.value })}
                  className="bg-slate-800 border-slate-700 text-white"
                  placeholder="Post-stroke aphasia"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-slate-300 text-sm">Notes</Label>
                <Input
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  className="bg-slate-800 border-slate-700 text-white"
                  placeholder="Additional notes…"
                />
              </div>

              {formError && (
                <p className="text-red-400 text-sm bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
                  {formError}
                </p>
              )}

              <div className="flex gap-3 pt-1">
                <Button
                  type="submit"
                  disabled={saving}
                  className="flex-1 bg-blue-600 hover:bg-blue-500 text-white"
                >
                  {saving ? "Saving…" : "Save Patient"}
                </Button>
                <Button
                  type="button"
                  onClick={() => setShowAddForm(false)}
                  variant="outline"
                  className="flex-1 border-slate-700 text-slate-300 hover:bg-slate-800"
                >
                  Cancel
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
