# LAN Testing Guide (Windows)

How to run the app so other computers on your local network can access it.

The backend serves both the API and the frontend on a single port (8000),
so there are no CORS issues — everything is same-origin.

---

## 1. Find your LAN IP

Open **Command Prompt** or **PowerShell** and run:

```
ipconfig
```

Look for your active adapter (usually **Wi-Fi** or **Ethernet**) and note the
**IPv4 Address**, e.g. `192.168.1.50`.

---

## 2. Start the server in LAN mode

In the project root, open a terminal and run:

```cmd
set HOST=0.0.0.0
python run.py
```

The server will print:

```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

This serves **both the API and the frontend** on port 8000.
No second terminal or separate frontend server needed.

> **Why no CORS_ORIGINS?** When the browser loads the page from
> `http://192.168.1.50:8000/login.html` and calls
> `http://192.168.1.50:8000/api/auth/login`, these are same-origin requests.
> CORS does not apply. The `CORS_ORIGINS` env var is only needed if you run
> a separate frontend dev server on a different port (see appendix).

---

## 3. Open Windows Firewall for port 8000

Open **PowerShell as Administrator** and run:

```powershell
netsh advfirewall firewall add rule name="IntakeEval 8000" dir=in action=allow protocol=TCP localport=8000
```

To remove this rule later:

```powershell
netsh advfirewall firewall delete rule name="IntakeEval 8000"
```

---

## 4. Verify from another PC

From any other computer on the same network, replace `192.168.1.50` with the
host machine's LAN IP.

### Test 1: Health check

```bash
curl http://192.168.1.50:8000/health
```

Expected:

```json
{"status": "ok"}
```

### Test 2: Auth login

```bash
curl -X POST http://192.168.1.50:8000/api/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"email\": \"student@test.com\", \"password\": \"password123\"}"
```

Expected: `200` with `token`, `student_id`, `role` — or `401` if the account
doesn't exist (confirms the server is reachable and processing requests).

### Test 3: Frontend in browser

Open a browser on the other PC and navigate to:

```
http://192.168.1.50:8000/login.html
```

The login page should render. Open DevTools (F12) > Console and confirm there
are no `NetworkError` or CORS errors.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `curl: (7) Failed to connect` | Firewall not opened (step 3) or server not started with `HOST=0.0.0.0` (step 2) |
| Page loads but login gives `NetworkError` | `localStorage.api_base` set to an old value. Open DevTools > Console and run `localStorage.removeItem('api_base')`, then reload. |
| `ERR_CONNECTION_REFUSED` | Server not running or wrong IP. Verify with `ipconfig` on the host. |

---

## Quick reference

```cmd
:: One terminal, one port, no CORS
set HOST=0.0.0.0
python run.py

:: Then open from any LAN computer:
::   http://192.168.1.50:8000/login.html
```

---

## Appendix: Separate frontend dev server (optional)

If you want to use a separate frontend server (e.g. for live-reload during
development), you can still run one on a different port:

```cmd
cd frontend
python -m http.server 5173 --bind 0.0.0.0
```

In this case, set CORS origins so the backend accepts requests from port 5173:

```cmd
set HOST=0.0.0.0
set CORS_ORIGINS=http://192.168.1.50:8000,http://192.168.1.50:5173,http://localhost:8000,http://localhost:5173
python run.py
```

Open firewall for both ports:

```powershell
netsh advfirewall firewall add rule name="IntakeEval 8000" dir=in action=allow protocol=TCP localport=8000
netsh advfirewall firewall add rule name="IntakeEval 5173" dir=in action=allow protocol=TCP localport=5173
```
