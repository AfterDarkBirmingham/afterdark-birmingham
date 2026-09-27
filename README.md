# AFTERDARK Birmingham — Launch MVP

A launch-ready Flask marketplace MVP for Birmingham's alternative scene.

## Included
- Customer/provider accounts
- Provider profiles, services, pricing and portfolio uploads
- Booking/enquiry workflow and customer booking account
- Reviews
- Admin control room
- Birmingham public directory listings, clearly marked as unclaimed
- Stripe Connect Express onboarding hook
- Stripe Checkout payment hook with a 12% illustrative platform fee
- Responsive AFTERDARK branding
- Render and Vercel deployment configuration

## Local run
python -m venv .venv
pip install -r requirements.txt
python app.py

Open http://127.0.0.1:5000

## First admin
Set AFTERDARK_ADMIN_EMAIL to the email used for the admin account. For a public launch, replace the simple email allow-list with a proper admin role/permissions system.

## Payments
Set STRIPE_SECRET_KEY to enable Stripe routes. Providers can connect a Stripe Express account from their dashboard. Customers can pay accepted bookings from My bookings. Before live payments, add Stripe webhook verification and persistent payment status reconciliation.

## Production notes
- Use managed PostgreSQL rather than SQLite for multi-instance production.
- Move portfolio uploads to object storage.
- Add CSRF, rate limiting, email verification, password reset, moderation, audit logs and backups.
- Add privacy policy, terms, cookie consent and UK data-protection review.
- Use HTTPS and production secrets.
