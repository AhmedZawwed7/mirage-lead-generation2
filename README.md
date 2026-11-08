# Mirage Leads Hunter

Arabic-first company lead discovery and contact extraction platform.

## cPanel package
The ready-to-upload package is named `Mirage-Leads-Hunter-Ready-for-cPanel.zip`.

## Deploy on cPanel
1. Upload and extract the package into your application directory.
2. Create a Python application in cPanel and select the application root.
3. Install dependencies from `requirements.txt`.
4. Configure environment variables using `.env.example` as a template. Never commit real credentials or API keys.
5. Set Passenger startup file to `passenger_wsgi.py` and restart the application.

## Security
- Do not commit `.env`, credentials, API keys, database files, or runtime data.
- WhatsApp Web automation is not enabled in cPanel mode.

See `README_AR.md` inside the package for the full Arabic setup guide.
