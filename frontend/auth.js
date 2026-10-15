const COGNITO_CONFIG = {
  domain: "https://us-east-1bzjxuygic.auth.us-east-1.amazoncognito.com",
  clientId: "163h04gavvfl93ap64uclcbjok",
  redirectUri: "http://127.0.0.1:5500/frontend/callback.html",
  scopes: "openid email profile",
  responseType: "code",
  tokenEndpoint: "https://us-east-1bzjxuygic.auth.us-east-1.amazoncognito.com/oauth2/token",
};

const EXPECTED_COGNITO_REDIRECT_URI = "http://127.0.0.1:5500/frontend/callback.html";

const AUTH_STORAGE_KEYS = {
  codeVerifier: "cognito_pkce_code_verifier",
  state: "cognito_oauth_state",
  idToken: "cognito_id_token",
  accessToken: "cognito_access_token",
  refreshToken: "cognito_refresh_token",
};

function base64UrlEncode(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";

  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function generateRandomString(byteLength = 32) {
  const randomBytes = new Uint8Array(byteLength);
  crypto.getRandomValues(randomBytes);
  return base64UrlEncode(randomBytes);
}

async function createCodeChallenge(codeVerifier) {
  const encodedVerifier = new TextEncoder().encode(codeVerifier);
  const digest = await crypto.subtle.digest("SHA-256", encodedVerifier);
  return base64UrlEncode(digest);
}

function parseJwtPayload(token) {
  try {
    const payload = token.split(".")[1];
    const normalizedPayload = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = atob(normalizedPayload);
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

function getIdToken() {
  return localStorage.getItem(AUTH_STORAGE_KEYS.idToken);
}

function getAccessToken() {
  return localStorage.getItem(AUTH_STORAGE_KEYS.accessToken);
}

function getUserSummary() {
  const idToken = getIdToken();

  if (!idToken) {
    return null;
  }

  const payload = parseJwtPayload(idToken);
  return {
    email: payload?.email || null,
    username: payload?.cognitoUsername || payload?.["cognito:username"] || payload?.sub || null,
  };
}

async function loginWithCognito() {
  if (COGNITO_CONFIG.redirectUri !== EXPECTED_COGNITO_REDIRECT_URI) {
    throw new Error(`Invalid Cognito redirect URI: ${COGNITO_CONFIG.redirectUri}`);
  }

  const codeVerifier = generateRandomString(64);
  const codeChallenge = await createCodeChallenge(codeVerifier);
  const state = generateRandomString(24);

  localStorage.setItem(AUTH_STORAGE_KEYS.codeVerifier, codeVerifier);
  localStorage.setItem(AUTH_STORAGE_KEYS.state, state);

  const params = new URLSearchParams({
    client_id: COGNITO_CONFIG.clientId,
    response_type: COGNITO_CONFIG.responseType,
    scope: COGNITO_CONFIG.scopes,
    redirect_uri: COGNITO_CONFIG.redirectUri,
    code_challenge_method: "S256",
    code_challenge: codeChallenge,
    state,
  });

  const loginUrl = `${COGNITO_CONFIG.domain}/oauth2/authorize?${params.toString()}`;
  console.log("Cognito Hosted UI login URL:", loginUrl);
  window.location.href = loginUrl;
}

async function exchangeCodeForTokens(code) {
  const codeVerifier = localStorage.getItem(AUTH_STORAGE_KEYS.codeVerifier);

  if (!codeVerifier) {
    throw new Error("Missing PKCE code verifier. Start the login flow again.");
  }

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: COGNITO_CONFIG.clientId,
    code,
    redirect_uri: COGNITO_CONFIG.redirectUri,
    code_verifier: codeVerifier,
  });

  const response = await fetch(COGNITO_CONFIG.tokenEndpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body,
  });

  const tokenData = await response.json();

  if (!response.ok) {
    const message = tokenData.error_description || tokenData.error || "Token exchange failed.";
    throw new Error(message);
  }

  localStorage.setItem(AUTH_STORAGE_KEYS.idToken, tokenData.id_token);
  localStorage.setItem(AUTH_STORAGE_KEYS.accessToken, tokenData.access_token);

  if (tokenData.refresh_token) {
    localStorage.setItem(AUTH_STORAGE_KEYS.refreshToken, tokenData.refresh_token);
  }

  localStorage.removeItem(AUTH_STORAGE_KEYS.codeVerifier);
  localStorage.removeItem(AUTH_STORAGE_KEYS.state);

  return tokenData;
}

async function handleCognitoCallback() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const state = params.get("state");
  const error = params.get("error");
  const errorDescription = params.get("error_description");

  if (error) {
    throw new Error(errorDescription || error);
  }

  if (!code) {
    throw new Error("Authorization code was not found in the callback URL.");
  }

  const expectedState = localStorage.getItem(AUTH_STORAGE_KEYS.state);
  if (!expectedState || state !== expectedState) {
    throw new Error("Login state did not match. Start the login flow again.");
  }

  return exchangeCodeForTokens(code);
}

function logout() {
  localStorage.removeItem(AUTH_STORAGE_KEYS.idToken);
  localStorage.removeItem(AUTH_STORAGE_KEYS.accessToken);
  localStorage.removeItem(AUTH_STORAGE_KEYS.refreshToken);
  localStorage.removeItem(AUTH_STORAGE_KEYS.codeVerifier);
  localStorage.removeItem(AUTH_STORAGE_KEYS.state);
}

window.Auth = {
  loginWithCognito,
  handleCognitoCallback,
  logout,
  getIdToken,
  getAccessToken,
  getUserSummary,
};
