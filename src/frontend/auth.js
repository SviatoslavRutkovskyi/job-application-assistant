const _IS_LOCAL = window.location.hostname === "localhost";

// Checks /.auth/me and returns the user object, or null if unauthenticated.
async function getUser() {
  if (_IS_LOCAL) return { userId: "dev" };
  try {
    const res = await fetch("/.auth/me");
    if (!res.ok) return null;
    const payload = await res.json();
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
  if (_IS_LOCAL) return; // skip profile check locally — backend dev mode handles it
  const res = await fetch("/api/v1/profile/exists");
  if (!res.ok) return;
  const { exists } = await res.json();
  if (!exists) {
    window.location.href = "/frontend/profile-setup.html";
  }
}

// Call on profile-setup.html — redirects to login if unauthenticated only.
async function requireAuth() {
  if (_IS_LOCAL) return;
  const user = await getUser();
  if (!user) {
    window.location.href = "/frontend/login.html";
  }
}
