import os
from flask import Flask, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import logging
import re

app = Flask(__name__)
CORS(app)

# --- Set up professional logging ---
app.logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)
# --- End of logging setup ---

# --- Firebase Admin SDK Initialization ---
db = None
try:
    cred = credentials.Certificate("/etc/secrets/firebase-credentials.json")
    firebase_admin.initialize_app(cred, {'projectId': 'r360v2'})
    db = firestore.client()
    app.logger.info("Firebase initialized successfully.")
except Exception as e:
    app.logger.error(f"Firebase credentials error: {e}")
# --- End of Firebase Initialization ---

def get_freepik_cookies():
    if not db:
        app.logger.error("Firestore client not available.")
        return None
    try:
        cookie_doc_ref = db.collection('config').document('freepik_cookies')
        doc = cookie_doc_ref.get()
        if doc.exists:
            app.logger.info("Successfully fetched cookie from Firestore.")
            return doc.to_dict().get('value')
        else:
            app.logger.warning("Cookie document 'config/freepik_cookies' does not exist.")
            return None
    except Exception as e:
        app.logger.error(f"Error fetching cookie from Firestore: {e}")
        return None

def parse_cookies_for_header(cookie_string):
    if not cookie_string:
        return ''
    return '; '.join([f"{parts[5]}={parts[6]}" for line in cookie_string.strip().split('\n') if line.strip() and not line.strip().startswith('#') and len(parts := line.strip().split('\t')) == 7])

# --- Updated Endpoint to Check Login Status ---
@app.route('/check-login', methods=['GET'])
def check_login():
    app.logger.info("Received a login check request.")
    
    cookie_string = get_freepik_cookies()
    if not cookie_string:
        return jsonify({'status': 'error', 'message': 'Could not retrieve Freepik cookies from database.'}), 500

    cookie_header = parse_cookies_for_header(cookie_string)
    if not cookie_header:
        return jsonify({'status': 'error', 'message': 'Failed to parse cookies.'}), 500

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        'Cookie': cookie_header,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8'
    }

    # We will go to a standard premium asset page to check the login status.
    test_url = "https://www.freepik.com/premium-vector/cute-cartoon-cats-various-breeds_417256328.htm"
    
    try:
        app.logger.info("Making request to a Freepik page to verify login status from HTML.")
        response = requests.get(test_url, headers=headers)
        response.raise_for_status() # Will throw an error for bad status codes like 4xx or 5xx

        # --- NEW, MORE RELIABLE CHECK ---
        # We search the returned HTML for `data-is-user-logged="true"`
        if 'data-is-user-logged="true"' in response.text:
            app.logger.info("Login check successful: Found 'data-is-user-logged=\"true\"' in HTML.")
            return jsonify({'status': 'success', 'message': 'Successfully logged into Freepik account.'})
        else:
            app.logger.warning("Login check failed: 'data-is-user-logged=\"true\"' not found. Cookies may be invalid.")
            return jsonify({'status': 'error', 'message': 'Login failed. The cookies appear to be invalid or expired.'}), 401
        # --- End of New Check ---

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Request to Freepik failed: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to connect to Freepik.'}), 502

# Health check for Render
@app.route('/health')
def health():
    return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 3000)))

