---
id: DOC-104
title: Connecting your employee directory to Docs
product: docs
---
## Before you begin
You need a directory admin account, the directory type (Cloud directory or LDAP) and the ability to create an API token in your directory.

## Connect a cloud directory
1. In Docs, open Workspace settings, then Integrations, then Directory.
2. Choose Connect directory and select your directory type.
3. Sign in with a directory admin account and approve the requested permissions.
4. Choose a sync schedule (hourly or daily) and select the groups to sync.
5. Choose Run first sync. The status changes to Connected when the first sync finishes.

## Connect an LDAP directory
1. Choose LDAP as the directory type.
2. Enter the server address, port 636 and a read-only service account.
3. Upload the CA certificate if your server uses a private certificate authority.
4. Choose Test connection, then Run first sync.

## What Connected means
The integration milestone is complete when the directory status shows Connected and at least one group has synced.
