# RAKSHAK — Demo Script

Step-by-step walkthrough for demonstrating RAKSHAK to judges. Each step has a **"Do this:"** action and a **"Say this:"** narration line.

---

## Setup (before demo)

**Do this:** Bring the stack up and seed it.

```bash
make up     # builds and starts postgres, redis, backend, dashboard
make seed   # four demo users + the MH12AB1234 hotlist entry
```

`make up` runs the Alembic migrations inside the backend container before uvicorn starts and waits for `http://localhost:8000/healthz`.

**Say this:** "RAKSHAK is a privacy-first ANPR network for stolen vehicle detection. Let me walk you through the full lifecycle."

---

## Step 1 — Open the dashboard

**Do this:** Open [http://localhost:5173](http://localhost:5173) in a browser.

**Say this:** "This is the police dashboard — the command center for tracking stolen vehicles."

---

## Step 2 — Log in as a police officer

**Do this:** Enter credentials:
- Email: `cop@rakshak.local`
- Password: `Cop@12345`

Click "Sign In".

**Say this:** "I'm logging in as a police officer. RBAC ensures only authorised personnel can access the hotlist and analytics."

---

## Step 3 — Show empty hotlist (if starting fresh)

**Do this:** Navigate to the hotlist page. If no entries exist yet, point out the empty state.

**Say this:** "Currently the hotlist is empty — no stolen vehicles have been reported yet."

---

## Step 4 — Citizen files a complaint

**Do this:** Open a new incognito/private browser window. Go to [http://localhost:5173](http://localhost:5173). Register or log in as the citizen user:
- Email: `citizen@rakshak.local`
- Password: `Cit@12345`

Navigate to the complaint page. Enter plate `MH12AB1234`. Submit.

**Say this:** "A citizen reports their vehicle stolen. They enter the licence plate number and submit a complaint. The plate is immediately normalised to the standard Indian format."

---

## Step 5 — Cop approves the complaint

**Do this:** Switch back to the police officer's browser. Refresh the hotlist page. The complaint should appear with status `PENDING_VERIFICATION`. Click "Approve" (or use the verify endpoint). The hotlist entry changes to `ACTIVE_UNCONFIRMED` with a 48-hour FIR deadline.

**Say this:** "The officer reviews the complaint, verifies ownership documents, and approves it. The plate is now on the hotlist — active and ready for detection. A WebSocket notification was pushed in real time."

---

## Step 6 — Device simulator sends a hit

**Do this:** In a terminal, run the device simulator (host-side; see `scripts/requirements-simulator.txt`):

```bash
python3 scripts/device_simulator.py \
  --video data/samples/sample1.mp4 \
  --plate MH12AB1234 \
  --device-email volunteer@rakshak.local \
  --device-password Vol@12345 \
  --lat 19.0760 \
  --lng 72.8777
```

**Say this:** "Now a volunteer's phone — or a government fleet vehicle — is scanning traffic. The on-device AI detects plates in real time. When it finds a match against the encrypted hotlist, it sends only the hit event to the server."

---

## Step 7 — Live map lights up

**Do this:** Switch to the police dashboard. Within 5 seconds, a toast notification appears. Navigate to the vehicle detail page for `MH12AB1234`. The map shows the sighting location with a marker, and the sighting details include the timestamp and confidence score. The photo itself is stored server-side and served from `/sightings/<file>` (known limitation 28: the dashboard does not render the thumbnail yet).

**Say this:** "The sighting just appeared on the dashboard — location, timestamp, confidence, and photo. The officer can see exactly where the stolen vehicle was spotted, in near real time."

---

## Step 8 — Analytics page

**Do this:** Navigate to the Analytics page. Show the overview metrics, heatmap, and time patterns.

**Say this:** "The analytics dashboard provides operational intelligence — active hotlist count, sighting trends, recovery rates, false positive rates per device, and temporal patterns that help allocate patrol resources."

---

## Step 9 — Revocation demo

**Do this:** As admin (`admin@rakshak.local` / `Admin@123`), revoke a device:

```bash
ADMIN_TOKEN="<get by logging in as admin>"
DEVICE_ID="<device-id-from-registration>"

curl -X POST "http://localhost:8000/api/v1/devices/${DEVICE_ID}/revoke" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Say this:** "If a device is compromised — stolen, lost, or tampered with — an admin can revoke it instantly. The device is cut off from the hotlist, and its local data is wiped on the next sync attempt."

---

## Step 10 — Privacy callout

**Do this:** Pause. Make eye contact.

**Say this:** "The most important thing about RAKSHAK is what it does *not* do. Non-matching plates are never stored, never transmitted. The backend never sees them. Every plate that is not on the hotlist is discarded within one frame loop, on-device. This is not a claim — it's architecturally enforced."

---

## Closing

**Do this:** Return to the dashboard overview.

**Say this:** "RAKSHAK gives law enforcement near real-time stolen vehicle detection while preserving citizen privacy by design. Thank you."

---

## Troubleshooting during demo

| Problem | Fix |
|---------|-----|
| Dashboard shows "Connection error" | Run `docker compose up -d` and wait 30s |
| Simulator says "No device token" | Remove `--device-token` flag; let it auto-register |
| No sighting appears | Check `MH12AB1234` is on the hotlist; check backend logs for ingestion errors |
| WebSocket not connecting | Rebuild the dashboard with `make up` so nginx proxies `/ws/` |
| Seed script fails | `make logs`; then retry `make seed` |
| Simulator exits with missing modules | `pip install -r scripts/requirements-simulator.txt` |
