// Checks /.auth/me and returns the user object, or null if unauthenticated.
async function getUser() {
  try {
    const res = await fetch("/.auth/me");
    if (!res.ok) return null;
    const payload = await res.json();
    // Easy Auth returns an array of client principals
    return payload?.clientPrincipal ?? null;
  } catch {
    return null;
  }
}

// Call on index.html — redirects to login if unauthenticated,
// redirects to profile setup if profile is incomplete.
async function requireAuthAndProfile() {
  const user = await getUser();
  if (!user) {
    window.location.href = "/frontend/login.html";
    return;
  }
  const res = await fetch("/api/v1/profile/exists");
  if (!res.ok) return; // network error — let the app handle it
  const { exists } = await res.json();
  if (!exists) {
    window.location.href = "/frontend/profile-setup.html";
  }
}

// Call on profile-setup.html — redirects to login if unauthenticated only.
// Does not check profile existence (that's what we're setting up).
async function requireAuth() {
  const user = await getUser();
  if (!user) {
    window.location.href = "/frontend/login.html";
  }
}
