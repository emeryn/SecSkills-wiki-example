# Authentication Flows

All flows go through Nginx (TLS, rate limits). Every state-changing request carries the CSRF token, `X-Requested-With` and an `Idempotency-Key`. Session cookie: `__Host-session; HttpOnly; Secure; SameSite=Lax; Path=/`.

## 1. Local sign-in
```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant B as Browser (SPA)
    participant N as Nginx
    participant A as Backend
    participant D as PostgreSQL
    B->>N: GET /api/v1/auth/csrf
    N->>A: forward
    A-->>B: pre-session cookie + CSRF token
    U->>B: username + password
    B->>N: POST /api/v1/auth/login (CSRF, Origin)
    N->>N: per-IP rate limit
    N->>A: forward (X-Forwarded-For, trusted proxy count)
    A->>A: check Origin / Sec-Fetch-Site, CSRF, blocked IP
    A->>D: auth_throttle for account and IP
    alt throttled
        A-->>B: 429 + Retry-After (same body for any account)
    else
        A->>D: find user by username
        Note over A: unknown user → verify against dummy Argon2id hash (equal timing)
        A->>A: Argon2id verify, rehash if parameters changed
        alt invalid or disabled
            A->>D: increment throttle, audit login_failed
            A-->>B: 401 INVALID_CREDENTIALS (generic)
        else honeytoken account
            A->>D: block IP, audit critical honeytoken_hit
            A-->>B: 401 INVALID_CREDENTIALS
        else valid
            A->>D: reset throttle, create session (new ID), revoke pre-session
            alt MFA enrolled or required (admin)
                A-->>B: 200 {next: "mfa"} session flagged mfa_pending
            else
                A->>D: audit login_success
                A-->>B: 200 {next: "app"} + new session cookie
            end
        end
    end
```

## 2. MFA challenge (TOTP or WebAuthn)
```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant B as Browser
    participant A as Backend
    participant D as PostgreSQL
    alt TOTP
        U->>B: 6-digit code
        B->>A: POST /api/v1/auth/mfa/totp
        A->>D: load secret, last_used_step
        A->>A: verify ±1 step, step > last_used_step
        A->>D: store last_used_step
    else WebAuthn
        B->>A: POST /api/v1/auth/mfa/webauthn/options
        A-->>B: challenge (stored in session, single use)
        U->>B: authenticator gesture
        B->>A: POST /api/v1/auth/mfa/webauthn/verify (assertion)
        A->>A: verify origin, rpId, signature, sign_count
    else Recovery code
        B->>A: POST /api/v1/auth/mfa/recovery
        A->>D: match hash, mark used
    end
    alt failure
        A->>D: throttle, audit mfa_failed
        A-->>B: 401
    else success
        A->>D: rotate session ID, set mfa_verified_at, audit login_success
        A->>D: known_devices lookup
        opt admin from unknown IP/device
            A->>A: send "New sign-in" notification, restrict destructive actions until re-confirmed
        end
        A-->>B: 200 + new session cookie
    end
```

## 3. Bootstrap admin first sign-in
```mermaid
sequenceDiagram
    autonumber
    actor O as Operator
    participant I as init container
    participant S as secrets volume
    participant A as Backend
    participant B as Browser
    I->>S: generate DB passwords, master key, bootstrap admin password (0600)
    A->>A: first boot: create admin (must_reset_password, MFA required)
    O->>S: make admin-password (read once, then file deleted)
    O->>B: sign in with bootstrap password
    B->>A: POST /auth/login
    A-->>B: 200 {next: "reset_password"} (restricted session)
    B->>A: POST /auth/password (new password, policy + breached list)
    A-->>B: 200 {next: "enroll_mfa"}
    B->>A: TOTP or WebAuthn enrollment + confirmation
    A->>A: rotate session, audit admin_bootstrap_completed
    A-->>B: 200 {next: "app"}
```

## 4. Password reset
```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant B as Browser
    participant A as Backend
    participant D as PostgreSQL
    participant M as SMTPS
    U->>B: email address
    B->>A: POST /api/v1/auth/password-reset (rate limited)
    A->>D: lookup by email_bidx
    opt account exists, local, enabled
        A->>D: store SHA-256(token), expires in 30 min, invalidate older tokens
        A->>M: link with token (CR/LF stripped headers)
    end
    A-->>B: 202 same response in all cases
    U->>B: open link, new password
    B->>A: POST /api/v1/auth/password-reset/confirm
    A->>D: find unused, unexpired token hash
    alt invalid, used or expired
        A-->>B: 400 generic
    else valid
        A->>D: set Argon2id hash, mark token used, revoke all sessions
        A->>D: audit password_reset
        A-->>B: 200 → sign-in page (MFA still required at next login)
    end
```

## 5. Step-up re-authentication (sensitive actions)
Applies to: space deletion, export of a whole space, membership/role changes by admins, user deletion, MFA changes.
```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as Backend
    B->>A: DELETE /api/v1/spaces/{space}
    A->>A: session.reauth_at older than 5 min?
    A-->>B: 401 REAUTH_REQUIRED
    B->>A: POST /api/v1/auth/reauth (password or MFA)
    A->>A: verify, set reauth_at, rotate session ID
    B->>A: retry DELETE with the same Idempotency-Key
    A-->>B: 204 + audit space_deleted
```

## 6. OIDC sign-in (optional extension)
```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant B as Browser
    participant A as Backend
    participant P as OIDC provider
    U->>B: "Sign in with SSO"
    B->>A: GET /api/v1/auth/oidc/start?next=/spaces/eng
    A->>A: validate next (relative, single leading /)
    A->>A: state, nonce, PKCE verifier → stored in pre-session
    A-->>B: 302 to authorize endpoint (code_challenge S256)
    B->>P: authenticate
    P-->>B: 302 /api/v1/auth/oidc/callback?code&state (SameSite=Lax keeps cookie)
    B->>A: callback
    A->>A: compare state
    A->>P: token request (code + verifier, client secret from *_FILE)
    P-->>A: ID token + access token
    A->>A: verify signature (JWKS), alg pinned, iss, aud, exp, nonce
    A->>A: provision or update user, map groups → space roles (source=sso)
    A->>A: new session, audit login_success (oidc)
    A-->>B: 302 to validated next
```

LDAPS follows flow 1 with the password check replaced by: service bind → escaped user filter search → user bind over LDAPS (certificate verified) → group search → role mapping.
