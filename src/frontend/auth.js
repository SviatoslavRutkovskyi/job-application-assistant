const _IS_LOCAL = window.location.hostname === "localhost";

// Checks /api/v1/auth/me and returns the user object, or null if unauthenticated.
async function getUser() {
  if (_IS_LOCAL) return { oid: "dev" };
  try {
    const res = await fetch("/api/v1/auth/me");
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// Call on index.html — redirects to login if unauthenticated,
// redirects to profile setup if profile is incomplete.
async function requireAuthAndProfile() {
  const user = await getUser();
  if (!user) {
    window.location.href = "/frontend/landing.html";
    return;
  }
  if (_IS_LOCAL) {
    document.body.style.display = "";
    return;
  }
  const res = await fetch("/api/v1/profile/exists");
  if (!res.ok) {
    document.body.style.display = "";
    return;
  }
  const { exists } = await res.json();
  if (!exists) {
    window.location.href = "/frontend/profile-setup.html";
    return;
  }
  document.body.style.display = "";
}

// Call on profile-setup.html — redirects to login if unauthenticated only.
async function requireAuth() {
  if (_IS_LOCAL) return;
  const user = await getUser();
  if (!user) {
    window.location.href = "/frontend/landing.html";
  }
}

// Use this for sign-in links. In local dev, go straight to the app.
function signIn() {
  if (_IS_LOCAL) {
    window.location.href = "/";
  } else {
    window.location.href = "/.auth/login/oidc?post_login_redirect_uri=/";
  }
}

// Use this instead of a plain href for sign-out links.
// In local dev, Azure's /.auth/logout doesn't exist — just navigate to landing.
function signOut() {
  if (_IS_LOCAL) {
    window.location.href = "/frontend/landing.html";
  } else {
    window.location.href =
      "/.auth/logout?post_logout_redirect_uri=/frontend/landing.html";
  }
}
