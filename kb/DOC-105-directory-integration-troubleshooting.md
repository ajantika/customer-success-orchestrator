---
id: DOC-105
title: Directory integration troubleshooting
product: docs
---
## Authentication error when connecting
If you see Authentication failed, sign out of the directory in your browser and retry with a directory admin account. Accounts that use multi-factor prompts must complete the prompt within two minutes. Confirm the service account password has not expired.

## Connection timed out
A timeout usually means the directory server cannot be reached. Ask your network admin to allow the Docs sync addresses listed in Workspace settings under Integrations. For LDAP, confirm port 636 is open for inbound traffic from those addresses.

## Directory connects but no groups sync
Open the sync log in Integrations and check the filter. Groups with more than 5,000 members are skipped. Confirm the groups you selected exist and that the service account can read their members.

## Attribute mapping errors
Docs needs a unique email attribute for every person. Entries without an email value are skipped. Map the email field in Directory settings, then choose Run sync.

## When to contact support
If you have confirmed credentials, network access and attribute mapping and the connection still fails, contact support with the sync log and the exact error message. See [[DOC-108]].
