# Security Policy

## Reporting
Please report security issues privately to the repository owner. Do not publish credentials, personal data, or exploitable details in public issues.

## Repository rules
- Never commit .env files, API keys, OAuth tokens, SMTP passwords, session secrets, database dumps, or customer exports.
- Use .env.example with placeholders only.
- Rotate any credential that was accidentally committed.
- Keep dependencies patched and review automated dependency alerts.

## Application requirements
Authentication and authorization must be enforced server-side. Use CSRF protection for state-changing browser requests, secure cookie settings, parameterized SQL, output escaping, rate limits, and audit logs.

The crawler must reject private, loopback, link-local, and cloud metadata IP ranges; revalidate DNS on redirects; restrict protocols to HTTP/HTTPS; cap response sizes and timeouts; and respect robots.txt and per-domain rate limits.
