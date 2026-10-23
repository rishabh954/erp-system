# Notification System Audit

**Reviewed:** 2026-10-23
**Status:** Tenant-context and channel-preference fixes implemented; this is a focused review, not an exhaustive audit of every notification producer or live delivery integration.

## Current implementation verified

- `apps/notifications/services.py` contains `NotificationService`. The service applies per-company notification preferences for in-app, email, SMS, WhatsApp, and push paths.
- `NotificationPreference` already includes `push_enabled`; the prior statement that push preferences were missing is stale.
- `NotificationService.send()` resolves the requested company and now skips recipients without an active `UserCompany` membership in that company.
- Bulk notification tasks now restrict recipients to active users with active membership in the task's company.
- Notification API lists, unread counts, mark-all-read, HTML lists, preference reads/writes, and delivery-log lists use the active company.
- HTML mark-read and API object lookup scope records to the recipient and active company. API state changes require `notifications.update`.
- Preference rows are keyed by user, company, and notification type, allowing a user's settings to differ across tenants.
- SMS and WhatsApp helper calls return without side effects during backup restoration.

## Regression coverage added

`apps/notifications/tests/test_tenant_notifications.py` covers active-company API list/count and mark-all-read, cross-company HTML mark-read rejection, active-company preference separation, update permission enforcement, direct service and bulk task recipient membership, push preference enforcement, and restore suppression for SMS/WhatsApp helpers.

## Remaining gaps

- The existing service and some older producers coexist; this pass did not migrate every direct notification creation path to `NotificationService`.
- The complete workflow engine, audit log views, retry/idempotency behavior, and provider delivery lifecycle were not exhaustively reviewed.
- Live Redis, Celery worker, email, SMS, WhatsApp, and push-provider integrations were not tested. SQLite tests do not establish production infrastructure behavior.
- Existing broader tenant tests provide coverage, but this is not proof that every module's recipient selection is company-safe.

## Historical claims reconciled

The older audit text claiming there was no `NotificationService`, no push preference, or no notification test suite no longer describes the repository. Those capabilities already existed before this review. This pass found the remaining gaps listed above and added focused regression coverage without introducing a new notification framework.
