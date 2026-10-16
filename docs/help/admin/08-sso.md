# Single sign-on

Users can sign in through an OpenID Connect provider (button on the sign-in page) or with their
directory credentials (LDAP, same form as local accounts). Configure either in **Settings >
OpenID Connect** or **Settings > LDAP directory**, or with `BACKEND_OIDC_*` / `BACKEND_LDAP_*`
variables: a field set by a variable is marked *set by environment* and cannot be changed here.
**Test connection** checks discovery and signing keys (OIDC) or the service bind and a sample
search (LDAP). Both need the egress overlay to reach the provider.

## OpenID Connect

- Register `<wiki URL>/api/v1/auth/oidc/callback` as redirect URI, as a confidential client.
- The issuer must match the provider's discovery document exactly. Tokens signed with another
  algorithm than the one selected are refused.
- Accounts are linked to the provider's subject identifier, never matched by name: when a local
  account already uses the same username, sign-in is refused.

## LDAP directory

- `ldaps://`, or `ldap://` with StartTLS; certificates are always verified (add an internal CA).
- The service account searches the user, then the user's password is checked by binding as them.
- A local account with the same username keeps signing in locally.

## Groups, accounts and administrators

- **Group to space role mapping**, one rule per line: `group | space key | role`. Memberships
  created this way are updated at each sign-in; memberships added by hand are never changed.
- **Create accounts at first sign-in** off: only accounts already linked can sign in.
- **Administrator groups**: members get the administrator role at sign-in and lose it when they
  leave every listed group (the last active administrator is never demoted). Like every
  administrator, they must use a second factor of the wiki after the provider: they enroll one at
  their first sign-in. Their role cannot be changed by hand.
- Keep at least one local administrator with a second factor: it still works when the provider
  is down.
- **Settings > Security > Local password sign-in: Administrators only** refuses local passwords
  for everyone else; each administrator sign-in then raises a critical alert (break-glass).
- To confirm a sensitive action, OpenID Connect users sign in again at the provider; directory
  users type their directory password.
