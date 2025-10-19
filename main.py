import os
import re
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import logging
import json

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

@app.route('/health')
def health():
    return 'OK', 200

@app.route('/download', methods=['POST'])
def download():
    app.logger.info("Received a download request.")
    data = request.get_json()
    freepik_url = data.get('freepikUrl')

    if not freepik_url:
        app.logger.warning("Request received without a Freepik URL.")
        return jsonify({'error': 'Freepik URL is required.'}), 400

    cookie_string = get_freepik_cookies()
    if not cookie_string:
        return jsonify({'error': 'Could not retrieve Freepik cookie from database.'}), 500
    
    cookie_header = parse_cookies_for_header(cookie_string)
    if not cookie_header:
        return jsonify({'error': 'Failed to parse cookies.'}), 500
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
        'Cookie': cookie_header,
        'Referer': freepik_url
    }

    try:
        # --- First, get the page HTML to find the necessary IDs ---
        app.logger.info(f"Fetching page HTML for URL: {freepik_url}")
        page_response = requests.get(freepik_url, headers=headers)
        page_response.raise_for_status()

        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page_response.text)
        if not match:
            app.logger.error("Could not find __NEXT_DATA__ script tag in page source.")
            return jsonify({'error': 'Could not parse page data. Site structure may have changed.'}), 500

        next_data = json.loads(match.group(1))
        
        resource_id = next_data.get('props', {}).get('pageProps', {}).get('id')
        wallet_id = next_data.get('props', {}).get('pageProps', {}).get('user', {}).get('wallet', {}).get('id')

        if not resource_id or not wallet_id:
            app.logger.error(f"Could not extract resource_id or wallet_id from page data.")
            return jsonify({'error': 'Could not extract necessary download parameters.'}), 500
            
        app.logger.info(f"Extracted resource ID: {resource_id} and wallet ID: {wallet_id}")

        # --- Use the API endpoint you discovered ---
        api_url = f"https://www.freepik.com/api/regular/download"
        payload = {
            "resource": resource_id,
            "action": "download",
            "walletId": wallet_id,
            "locale": "en"
        }
        
        api_headers = headers.copy()
        api_headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json;charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
        })

        app.logger.info(f"Making API call for resource {resource_id}")
        api_response = requests.post(api_url, headers=api_headers, json=payload)
        api_response.raise_for_status()
        
        response_data = api_response.json()
        final_download_url = response_data.get('url')

        if not final_download_url:
            app.logger.error("API response did not contain a download URL.")
            return jsonify({'error': 'Could not get download link from Freepik API.'}), 500
            
        app.logger.info("Successfully got final download URL.")

        # --- Stream the file to the user ---
        file_response = requests.get(final_download_url, stream=True)
        file_response.raise_for_status()
        
        content_disposition = file_response.headers.get('content-disposition')
        
        return Response(file_response.iter_content(chunk_size=8192),
                        content_type=file_response.headers['content-type'],
                        headers={"Content-Disposition": content_disposition})

    except requests.exceptions.RequestException as e:
        app.logger.error(f"API request failed: {e}")
        if e.response is not None:
             app.logger.error(f"Response status: {e.response.status_code}")
             app.logger.error(f"Response body: {e.response.text}")
        return jsonify({'error': 'Failed to communicate with Freepik API. Cookies may be expired.'}), 502

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 3000)))

