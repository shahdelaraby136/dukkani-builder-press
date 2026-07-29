# Press site synchronization

Every new store submitted to `POST /tenants` must be represented by a Press
`Site` document on the active Dukkani bench.

The canonical production bench and Docker container are both:

`bench-0001-000007-dukkanip`

Provisioning follows these rules:

1. A brand-new store is created through Press Agent.
2. A resumed store whose physical site already exists is registered in Press
   without running another `New Site` Agent job.
3. Press registration is idempotent: an existing Press `Site` is reused.
4. Legacy stores on the old Docker stack are not falsely attached to the
   active Press bench.
5. `verify_required_routes.py` fails deployment if the Press creation or
   resumed-site registration steps are removed, or if the container and Press
   bench drift apart.
