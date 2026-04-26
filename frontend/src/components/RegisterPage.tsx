import { useState } from "react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { api } from "@/lib/api";

interface Props {
  onSuccess: () => void;
  onBackToLogin: () => void;
}

function passwordError(pw: string): string {
  if (pw.length < 8) return "Must be at least 8 characters";
  if (!/[A-Z]/.test(pw)) return "Must contain at least one uppercase letter";
  if (!/[0-9]/.test(pw)) return "Must contain at least one number";
  return "";
}

const empty = { full_name: "", username: "", password: "", confirm: "" };

export default function RegisterPage({ onSuccess, onBackToLogin }: Props) {
  const [form, setForm] = useState(empty);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const set = (k: keyof typeof empty) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((prev) => ({ ...prev, [k]: e.target.value }));

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (!form.full_name.trim()) errs.full_name = "Required";
    if (!form.username.trim()) errs.username = "Required";
    const pwErr = passwordError(form.password);
    if (pwErr) errs.password = pwErr;
    if (form.password !== form.confirm) errs.confirm = "Passwords do not match";
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!validate()) return;
    setLoading(true);
    try {
      await api("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          username: form.username.trim(),
          full_name: form.full_name.trim(),
          password: form.password,
        }),
      });
      onSuccess();
    } catch (err: any) {
      setError(err?.message ?? "Registration failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white tracking-tight">SpeakWithMe</h1>
          <p className="text-slate-400 mt-1 text-sm">Medical Communication System</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-2xl">
          <h2 className="text-lg font-semibold text-white mb-6">Create your account</h2>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="reg-full-name" className="text-slate-300 text-sm">
                Full Name
              </Label>
              <Input
                id="reg-full-name"
                autoFocus
                value={form.full_name}
                onChange={set("full_name")}
                placeholder="Dr. Jane Smith"
                className={`bg-slate-800 border-slate-700 text-white placeholder:text-slate-500 focus:border-blue-500 ${fieldErrors.full_name ? "border-red-700" : ""}`}
              />
              {fieldErrors.full_name && <p className="text-red-400 text-xs mt-1">{fieldErrors.full_name}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="reg-username" className="text-slate-300 text-sm">
                Username
              </Label>
              <Input
                id="reg-username"
                autoComplete="username"
                value={form.username}
                onChange={set("username")}
                placeholder="jsmith"
                className={`bg-slate-800 border-slate-700 text-white placeholder:text-slate-500 focus:border-blue-500 ${fieldErrors.username ? "border-red-700" : ""}`}
              />
              {fieldErrors.username && <p className="text-red-400 text-xs mt-1">{fieldErrors.username}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="reg-password" className="text-slate-300 text-sm">
                Password
              </Label>
              <Input
                id="reg-password"
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={set("password")}
                placeholder="Min. 8 chars, 1 uppercase, 1 number"
                className={`bg-slate-800 border-slate-700 text-white placeholder:text-slate-500 focus:border-blue-500 ${fieldErrors.password ? "border-red-700" : ""}`}
              />
              {fieldErrors.password && <p className="text-red-400 text-xs mt-1">{fieldErrors.password}</p>}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="reg-confirm" className="text-slate-300 text-sm">
                Confirm Password
              </Label>
              <Input
                id="reg-confirm"
                type="password"
                autoComplete="new-password"
                value={form.confirm}
                onChange={set("confirm")}
                placeholder="Repeat your password"
                className={`bg-slate-800 border-slate-700 text-white placeholder:text-slate-500 focus:border-blue-500 ${fieldErrors.confirm ? "border-red-700" : ""}`}
              />
              {fieldErrors.confirm && <p className="text-red-400 text-xs mt-1">{fieldErrors.confirm}</p>}
            </div>

            {error && (
              <p className="text-red-400 text-sm bg-red-950/40 border border-red-900 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <Button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white font-medium h-10"
            >
              {loading ? "Creating account…" : "Create Account"}
            </Button>
          </form>

          <div className="mt-5 text-center">
            <button
              type="button"
              onClick={onBackToLogin}
              className="text-slate-400 text-sm hover:text-slate-200 transition-colors"
            >
              ← Back to Sign In
            </button>
          </div>
        </div>

        <p className="text-center text-slate-600 text-xs mt-6">
          SpeakWithMe — AAC for nonverbal patients
        </p>
      </div>
    </div>
  );
}
