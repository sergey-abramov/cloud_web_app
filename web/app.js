const CLIENT_ID = 'aje22riv1e41161ls8ch';
const AUTH_URL = 'https://auth.yandex.cloud/oauth/authorize';
const API_BASE = 'https://d5dbieh1fdvcu3dhdl1a.kf69zffa.apigw.yandexcloud.net';

const loginBtn = document.getElementById('loginBtn');
const logoutBtn = document.getElementById('logoutBtn');
const statusDiv = document.getElementById('status');
const userDataDiv = document.getElementById('userData');

function login() {
    const redirectUri = window.location.origin + '/callback.html';
    const authUrl = `${AUTH_URL}?client_id=${CLIENT_ID}&response_type=id_token&scope=openid email profile&redirect_uri=${encodeURIComponent(redirectUri)}&nonce=random123`;
    window.location.href = authUrl;
}

function logout() {
    localStorage.removeItem('id_token');
    location.reload();
}

async function fetchUser() {
    const token = localStorage.getItem('id_token');
    if (!token) {
        statusDiv.textContent = 'Not authenticated';
        loginBtn.style.display = 'block';
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/api/user`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
            const data = await res.json();
            statusDiv.textContent = 'Authenticated';
            userDataDiv.textContent = JSON.stringify(data, null, 2);
            userDataDiv.style.display = 'block';
            logoutBtn.style.display = 'block';
        } else {
            throw new Error('Unauthorized');
        }
    } catch (err) {
        statusDiv.textContent = 'Auth failed';
        localStorage.removeItem('id_token');
        loginBtn.style.display = 'block';
    }
}

loginBtn.addEventListener('click', login);
logoutBtn.addEventListener('click', logout);
fetchUser();