# Source Policy

## Allowed
- Official APIs.
- Public/permissioned feeds.
- Public company career pages where access is allowed.
- User-operated/manual approval flows.

## Restricted
A source may be indexed for research but not auto-submitted unless the integration explicitly permits it.

## Prohibited implementation patterns
- CAPTCHA bypass.
- Cookie/session theft.
- Password storage for bot use.
- Stealth browser automation intended to evade detection.
- Rate-limit circumvention.
- Scraping that violates the source's terms.

## LinkedIn
Treat LinkedIn as an approval/manual lane unless an authorized integration is available. Never ask the user to paste a password or OTP into application settings.
