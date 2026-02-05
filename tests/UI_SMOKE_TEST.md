# UI Smoke Test Checklist

## Prerequisites

1. **Start backend:**
   ```
   cd intake_eval_school
   .venv\Scripts\activate          # Windows
   python run.py                   # Starts on http://127.0.0.1:8000
   ```
   Verify: `curl http://127.0.0.1:8000/health` returns `{"status":"ok"}`

2. **Start frontend static server:**
   ```
   cd intake_eval_school\frontend
   python -m http.server 5173      # Starts on http://127.0.0.1:5173
   ```

3. **Open browser** to `http://127.0.0.1:5173/login.html`

---

## Test Cases

### A. Registration & Login

- [ ] Go to `http://127.0.0.1:5173/register.html`
- [ ] Register a **student** account (name, email, password, role=Student)
- [ ] After registration, page redirects to `student_dashboard.html`
- [ ] Click **Logout** in the nav bar
- [ ] Page redirects to `login.html`
- [ ] Log back in with the student credentials
- [ ] After login, page redirects to `student_dashboard.html` (not teacher dashboard)

### B. Teacher Registration & Login

- [ ] Go to `http://127.0.0.1:5173/register.html`
- [ ] Register a **teacher** account (role=Teacher)
- [ ] After registration, page redirects to `dashboard.html` (teacher dashboard)
- [ ] Verify the "Students" list is visible
- [ ] Click **Logout**, then log back in as teacher
- [ ] Redirects to `dashboard.html`

### C. Role Guards

- [ ] While logged in as **student**, navigate to `http://127.0.0.1:5173/dashboard.html`
- [ ] Should auto-redirect to `student_dashboard.html`
- [ ] While logged in as **teacher**, navigate to `http://127.0.0.1:5173/student_dashboard.html`
- [ ] Should auto-redirect to `dashboard.html`

### D. Student Dashboard

- [ ] Log in as **student**
- [ ] `student_dashboard.html` loads without errors
- [ ] Welcome message shows the student's name
- [ ] Level badge shows current level (or `--` if no assessment)
- [ ] Quick action buttons are visible (Session, Vocabulary, Conversation, Games, Recall)
- [ ] "Upcoming Sessions" section is visible
- [ ] "Schedule a Class" button is visible

### E. Assessment Flow

- [ ] From student dashboard, click **Take Assessment**
- [ ] `assessment.html` loads with student ID in URL
- [ ] Start the assessment -- 5 placement questions appear
- [ ] Answer all placement questions and submit
- [ ] Diagnostic questions appear (grammar, vocabulary, reading)
- [ ] Answer all diagnostic questions and submit
- [ ] Results page shows: determined level, sub-skill breakdown, recommendations
- [ ] **"Go to Dashboard"** button works -- navigates to `student_dashboard.html`
- [ ] Student dashboard now shows the determined level in the badge

### F. Scheduling -- Student Side

- [ ] On `student_dashboard.html`, click **"+ Schedule a Class"**
- [ ] Form appears with date/time picker, duration dropdown, and notes field
- [ ] Select a future date, keep 60 min, add a note
- [ ] Click **"Send Request"**
- [ ] Success message appears: "Session requested!"
- [ ] Form hides after ~1.5 seconds
- [ ] Session appears in the "Upcoming Sessions" list with status **Pending / Oczekujaca** (yellow)
- [ ] Click **"Cancel"** button on the form to verify it hides without submitting

### G. Scheduling -- Teacher Side

- [ ] Log in as **teacher**
- [ ] `dashboard.html` loads
- [ ] "Session Requests" panel is visible at the top
- [ ] The student's requested session appears with student name, date, time, duration
- [ ] Click **"Confirm"** on the session
- [ ] Session status changes to **Confirmed** (green)
- [ ] Confirm button disappears, Cancel button remains
- [ ] Click **Refresh** button to verify the list updates

### H. Scheduling -- Student Sees Confirmation

- [ ] Log in as **student**
- [ ] Go to `student_dashboard.html`
- [ ] The session now shows status **Confirmed / Potwierdzona** (green)
- [ ] Teacher name is displayed next to the session

### I. Scheduling -- Cancel Flow

- [ ] Log in as **teacher**
- [ ] Request another session as student first (or use an existing one)
- [ ] Click **"Cancel"** on a session
- [ ] Confirm the cancellation dialog
- [ ] Session status changes to **Cancelled** (red)
- [ ] Log in as student -- session shows as Cancelled

### J. Navigation Consistency

- [ ] Click every nav link on the student dashboard -- all load correctly
- [ ] Click every nav link on the teacher dashboard -- all load correctly
- [ ] No page shows a 404 or blank screen
- [ ] All pages have proper back-to-dashboard links that work
- [ ] Browser back/forward buttons work correctly

---

## Expected Results

All checkboxes above should pass. If any fail:
1. Check browser console for JavaScript errors
2. Verify backend is running: `curl http://127.0.0.1:8000/health`
3. Verify API_BASE in `frontend/js/api.js` is `http://127.0.0.1:8000`
4. Run `python tests/e2e_verify.py` to isolate API-level issues
