# Security and Privacy

HR Hunter can process candidate identity and CV data, recruiter details, applications, email content and integration credentials.

## Public repository boundary
The portfolio repository must not contain real candidate personal data, source CVs, real generated applications, credentials or tokens, operational databases, WAL/SHM files, logs, message histories, recruiter queues, local machine paths or historical application outputs.

Secrets must be supplied through local configuration and never committed. Example configuration contains placeholders only.

The original working environment remains private. Any public version is a sanitized representation intended to demonstrate architecture, product decisions and implementation patterns without exposing personal or operational data.
