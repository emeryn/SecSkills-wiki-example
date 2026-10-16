# Users and groups

- **New user** creates the account and an invitation link. Send it through a trusted channel: it
  works once. Password reset links are created from the user page in the same way.
- Changing a role or disabling an account signs the user out everywhere.
- **Reset two-factor authentication** removes every factor of a user who lost them.
- Accounts without a sign-in for 180 days (`BACKEND_INACTIVE_ACCOUNT_DAYS`) are disabled
  automatically. The last active administrator never is.
- Decoy usernames (see [Honeytokens](/help/admin/honeytokens)) cannot be given to accounts.
- Groups grant space roles to many users at once.

Role changes, resets and disabling ask you to confirm your identity.
