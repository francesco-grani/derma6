# API Reference

Base URL: `http://localhost:8000`  
Interactive docs: `http://localhost:8000/docs`

All protected endpoints require `Authorization: Bearer <token>`.

---

## Auth

### `POST /auth/register`

Create a new user account.

**Body:**
```json
{ "username": "alice", "password": "secret" }
```

**Response `200`:**
```json
{ "access_token": "<jwt>", "token_type": "bearer" }
```

---

### `POST /auth/login`

**Body:** `application/x-www-form-urlencoded` — `username`, `password`

**Response `200`:**
```json
{ "access_token": "<jwt>", "token_type": "bearer" }
```

---

## Chat

### `POST /chat/stream`

Stream a chat response as SSE (`text/event-stream`).

**Body:**
```json
{ "message": "What moisturiser should I use?", "session_id": "<uuid>" }
```

**SSE events:**

| `data` shape | Meaning |
|---|---|
| `{"token": "word"}` | LLM output token |
| `{"tool_call": {"name": "...", "result": "..."}}` | Tool fired |
| `{"cost": {"input_tokens": N, "output_tokens": N, "total_usd": N}}` | Turn cost |
| `{"error": "message"}` | Error occurred |

---

## Sessions

### `GET /sessions/me`

List all sessions for the current user, newest first.

**Response `200`:**
```json
[
  { "session_id": "<uuid>", "title": "Moisturiser advice", "created_at": "...", "updated_at": "..." }
]
```

---

### `POST /sessions/me`

Create a new session.

**Response `200`:**
```json
{ "session_id": "<uuid>", "title": "New chat", "created_at": "...", "updated_at": "..." }
```

---

### `GET /sessions/me/{session_id}/messages`

Retrieve message history for a session.

**Response `200`:**
```json
[
  { "role": "user", "content": "...", "created_at": "..." },
  { "role": "assistant", "content": "...", "created_at": "..." }
]
```

---

### `DELETE /sessions/me/{session_id}`

Delete a session and all its messages.

---

### `PATCH /sessions/me/{session_id}`

Rename a session.

**Body:** `{ "title": "New title" }`

---

## Profile

### `GET /profile/me`

Return the current user's skin profile.

**Response `200`:** full `UserProfile` schema (skin type, concerns, medical flags, routines, introduction plan).

---

### `PATCH /profile/me`

Update one or more profile fields.

**Body:** partial `UserProfile` — any subset of fields.

---

## Routines

### `GET /routines/me`

Return saved AM and PM routines.

---

### `POST /routines/me`

Save a new routine (overwrites the existing one for the same time-of-day).

**Body:** `{ "time_of_day": "AM" | "PM", "steps": [...] }`

---

## Skin Analysis

### `POST /analysis/skin`

Upload a photo for vision-based skin analysis. Streams SSE in the same format as `/chat/stream`.

**Body:** `multipart/form-data` — field `file` (image/jpeg or image/png, max 10 MB).

---

## Export

### `GET /export/html`

Export the current user's profile + routines + last session as an HTML document.

**Response:** `text/html` file download.

---

### `GET /export/pdf`

Same as HTML but rendered to PDF via WeasyPrint.

**Response:** `application/pdf` file download.

---

## Admin

Protected — requires `role = "admin"`.

### `GET /admin/users`

List all users.

### `DELETE /admin/users/{username}`

Delete a user and all their data.

---

## Health

### `GET /health`

Always returns `{ "status": "ok" }`. No auth required.
