# Notification System Audit

## Scope
This audit reviewed the current Django ERP notification architecture across the notifications app, workflow engine, inventory alerting, and related service code.

## Current architecture
- `apps/notifications/models.py` contains the core notification models: `Notification`, `EmailLog`, `SMSLog`, `WhatsAppLog`, and `NotificationPreference`.
- `apps/notifications/tasks.py` contains the Celery tasks for sending emails and bulk in-app notifications.
- `apps/notifications/views.py` exposes the notification list, preference management, and admin log views.
- `apps/notifications/urls.py` wires the notification pages and API endpoints.
- `apps/workflow/engine.py` sends workflow notifications with in-app, email, and WhatsApp logic.
- `core/services.py` exposes a generic `BaseService.send_notification` helper for app-level notifications.
- Multi-company data is scoped through `CompanyScoped` models and requires explicit company assignment on business records.

## Existing notification flows
- In-app notifications are stored in `Notification` and surfaced through the notification bell and list views.
- Bulk notifications are queued via Celery `send_bulk_notification`.
- Workflow events call `_send_notifications` and may notify assignees via in-app, email, and WhatsApp paths.
- Email sending is handled by `send_email_task` and stores `EmailLog` records.
- SMS and WhatsApp integrations are represented by `SMSLog` and `WhatsAppLog` models and are expected to be channel-aware.

## Duplicate and fragmented notification logic
Several code paths create notifications independently instead of routing through a single service:
- `core/services.py` directly calls `Notification.objects.create(...)`.
- `apps/workflow/engine.py` directly creates notifications in `_send_notifications`.
- `apps/notifications/tasks.py` bulk-creates notifications without a preference gate.
This fragmentation makes it harder to enforce tenant isolation, preference checks, and consistent logging.

## Missing functionality and hardening gaps
- There was no central `NotificationService` abstraction.
- Preference checks were not enforced centrally; `NotificationPreference` existed but was not used as an authoritative source of truth.
- The `NotificationPreference` model lacked the `push_enabled` channel used by the ERP notification requirements.
- Logs were created without consistent company assignment, which is a risk for multi-company tenant isolation.
- Direct email and WhatsApp calls bypassed notification preference logic and central logging.
- Template and channel routing relied on per-call conditions rather than a single service contract.

## Security problems
- Notification persistence and delivery logic was spread across modules, increasing the chance of unsafe or inconsistent behavior.
- Some paths did not validate user/company relationships before creating records.
- Email and external-channel logic would still fire even if a user had disabled the channel.

## Tenant-isolation problems
- Notification records are company-scoped, but not all creation paths guaranteed the correct `company` value.
- Preference records were user-scoped but not always resolved with the active company context.
- Notification lookups should always filter by both user and company; this was not guaranteed in every call site.

## Celery problems
- Celery tasks were used for email and bulk notifications, but the service layer was not enforcing the same quality checks across every task.
- Task payloads did not consistently enforce channel preferences or tenant data.

## Redis problems
- The ERP uses Redis/Celery infrastructure for async delivery, but notification dispatch was not centralized behind a single preference-aware service layer.
- There was no single place to validate queueing policy or deduplicate notification sends.

## Preference problems
- `NotificationPreference` existed but was not used to control notification delivery centrally.
- In-app and email preferences were not consistently checked before a message was created or queued.
- SMS and WhatsApp preferences existed but were not consistently enforced.
- Push preferences were missing completely.

## API problems
- Notification APIs were implemented, but they were not centrally enforcing the same channel and preference rules as the task/service code.
- There was no single service contract for creating, updating, and querying notifications across modules.

## UI problems
- The notification preference template showed in-app, email, SMS, and WhatsApp toggles but did not support push.
- The UI relied on the underlying preference model without a central coordinator to keep channels consistent.

## Testing gaps
- No explicit notification test suite was present to guard preference behavior, tenant correctness, or channel gating.
- There were no tests validating a notification event respects disabled channels.

## Performance risks
- Direct independent notification loops across modules can cause repeated database writes and redundant task dispatch.
- Bulk notification creation lacked central filtering on preferences and tenant scope.
- Email tasks rendered context without consistent guardrails on missing company or invalid user data.

## Conclusion
The notification subsystem was functional but fragmented. The safest upgrade is to centralize all creation, filtering, and logging in a single `NotificationService` and make preferences the single source of truth for every channel.
