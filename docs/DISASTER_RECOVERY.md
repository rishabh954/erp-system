# Enterprise ERP Disaster Recovery & Backup Plan

## Overview
This document outlines the standard operating procedures (SOP) for disaster recovery, database backups, point-in-time recovery (PITR), and high availability configuration for the PostgreSQL database backing the ERP.

## 1. Backup Strategy

### Continuous Archiving (WAL)
We utilize `pgBackRest` or `wal-g` for continuous Write-Ahead Log (WAL) archiving to an off-site object storage bucket (e.g., AWS S3, Google Cloud Storage).
- **RPO (Recovery Point Objective):** 5 minutes.
- **RTO (Recovery Time Objective):** < 1 hour.

### Daily Full Backups
Full snapshots of the database are taken daily at 02:00 AM UTC.
- Retention: 30 days.

### Weekly Logical Backups (pg_dump)
For portability and schema inspection, a logical dump is generated every Sunday.
```bash
pg_dump -U erp_user -h db -F c erp_db > /backups/erp_logical_weekly.dump
```
- Retention: 90 days.

## 2. Recovery Procedures

### Scenario A: Database Corruption or Accidental Drop (PITR)
If data corruption occurs, perform a Point-In-Time Recovery to the moment before the incident.
1. Stop the application containers.
2. Initialize a fresh PostgreSQL instance.
3. Configure `recovery.signal` and `restore_command`.
4. Set `recovery_target_time = 'YYYY-MM-DD HH:MM:SS'`.
5. Start PostgreSQL and wait for WAL replay to complete.
6. Verify data integrity.
7. Restart application containers.

### Scenario B: Complete Server Loss
1. Provision a new server instance via Terraform/Ansible.
2. Mount the remote backup volume or configure S3 access.
3. Restore the latest daily full backup.
4. Replay WAL files up to the last available transaction.
5. Update DNS records to point to the new server.

## 3. High Availability (HA)
For critical production deployments, the database should be run in a highly available configuration:
- **Primary Node:** Handles read/write traffic.
- **Standby Node (Synchronous):** Mirrors the primary. `synchronous_commit = on`.
- **Connection Pooler:** `PgBouncer` routes connections and handles failover routing.

## 4. Testing Backups
Backups must be tested monthly:
1. Automated CI/CD cron job pulls the latest daily backup.
2. Restores it into an isolated ephemeral container.
3. Runs the test suite and data consistency checks (e.g. `apps/accounting/management/commands/verify_ledgers.py`).
4. Sends an alert to the DevOps channel upon completion or failure.
