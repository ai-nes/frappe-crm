# Campaign routing options

`GET /api/method/crm.api.campaign.get_campaign_routing_options` returns routing
lookup metadata to authenticated users with read permission on `CRM Campaign`,
including Sale and CTV Sale. Guest users and users without Campaign read
permission receive 403.

The response contains:

- `teams`: active Sales teams, with `name`, `team_name`, `campus`, and `group`.
- `groups`: active team groups, with `name`, `group_name`, and `province`.

Each list contains at most 5,000 records. This endpoint uses Campaign read
permission for these lookup fields; callers do not need direct read permission
on `CRM Team` or `CRM Team Group`. Campaign mutations retain their existing
permission checks.
