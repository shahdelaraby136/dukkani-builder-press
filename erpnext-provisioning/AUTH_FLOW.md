# Dukkani authentication flow

This is the canonical authentication contract. Merchant and storefront
customer identities must remain separate.

## Merchants

- Central login: `https://dukani.ai/login`
- Central signup: `https://dukani.ai/signup`
- Successful login resolves the merchant's store and authenticates against
  that tenant before redirecting to `/desk`.
- Tenant `/login` uses the native Frappe login page.
- Tenant `/signup` redirects to the central merchant signup.
- Legacy `/merchant-access` is redirect-only and must never render a second
  login form.

## Storefront customers

- Login: `https://<store>.dukani.ai/customer-login`
- Signup: `https://<store>.dukani.ai/customer-signup`
- Account: `https://<store>.dukani.ai/customer-account`
- Orders: `https://<store>.dukani.ai/customer-orders`
- Customers are Frappe `Website User` accounts with the `Customer` role.
- Customer authentication must never grant access to `/desk`.

## Source-control safety

Runtime account, tenant, OAuth identity, log, backup, and cache files are
excluded by `.gitignore` and must not be committed.
