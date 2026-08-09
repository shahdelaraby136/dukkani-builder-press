# Dukani Marketing

Custom Frappe app foundation for Dukani marketing and customer-service workflows.

The first release intentionally supports drafting and an explicit approval flow. Publishing,
WhatsApp, and MCP write actions are separate follow-up capabilities that require provider
credentials and a completed security review.

## Security boundary

- The current Frappe site (`frappe.local.site`) is the tenant boundary.
- A request cannot choose or override its tenant site.
- Draft creation requires an authenticated user with the `Dukani Marketing User` role.
- Submission moves content to `Pending Approval`.
- Only `System Manager` can approve or reject content.
- Publishing is not exposed by this release.

## Installation (on a bench)

```bash
bench get-app /path/to/dukkani_marketing
bench --site <site> install-app dukani_marketing
bench --site <site> migrate
```

This repository is only the application source. Marketplace publication requires a
separate app repository, release metadata, review, and a Marketplace submission.
