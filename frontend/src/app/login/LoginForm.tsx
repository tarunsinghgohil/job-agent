"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { Button } from "../../components/Button";
import { Input } from "../../components/Field";
import { errorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      router.replace("/");
    } catch (err) {
      setError(errorMessage(err));
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-card">
      <div className="auth-brand">
        <span className="brand-mark" aria-hidden="true">
          JA
        </span>
        <span className="brand-text">
          <strong>Job Agent</strong>
          <small>Career operations</small>
        </span>
      </div>

      <h1>Sign in</h1>
      <p className="page-desc">Use the account credentials configured for this deployment.</p>

      <form onSubmit={handleSubmit} noValidate>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <Input
          label="Email"
          type="email"
          name="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={submitting}
        />
        <Input
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={submitting}
        />
        <div style={{ marginTop: 18 }}>
          <Button
            type="submit"
            variant="primary"
            loading={submitting}
            loadingLabel="Signing in…"
            className="btn-block"
            style={{ width: "100%" }}
          >
            Sign in
          </Button>
        </div>
      </form>
    </div>
  );
}
