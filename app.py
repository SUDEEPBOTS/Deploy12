from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from pymongo import MongoClient
import requests
import os
import secrets
import traceback
import random

app = Flask(__name__)
app.secret_key = "debug_secret_key_123"

# --- CONFIG ---
MONGO_URL = os.getenv("MONGO_URL")
UPTIME_SERVICE_URL = "https://uptimebot-rvni.onrender.com/add"

client = None
db = None
settings_col = None
db_error = None

# Backup Credentials
FIXED_API_KEY = "rnd_NTH8vbRYrb6wSPjI9EWW8iP1z3cV"
FIXED_OWNER_ID = "tea-d5kdaj3e5dus73a6s9e0"

try:
    if not MONGO_URL:
        db_error = "MONGO_URL Missing!"
    else:
        client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        db = client["DeployerBot"]
        settings_col = db["settings"]
        client.server_info()
except Exception as e:
    db_error = str(e)

# --- HELPERS ---
def get_settings():
    if settings_col is None: return {"repo": "", "api_data": ""}
    try:
        data = settings_col.find_one({"_id": "config"})
        return data if data else {"repo": "", "api_data": ""}
    except:
        return {"repo": "", "api_data": ""}

def get_all_accounts_list(shuffle=False):
    config = get_settings()
    raw_data = config.get("api_data", "")
    account_list = []
    if raw_data:
        lines = [line.strip() for line in raw_data.split('\n') if line.strip()]
        for line in lines:
            parts = line.split(',')
            if len(parts) >= 1:
                key = parts[0].strip()
                owner = parts[1].strip() if len(parts) >= 2 and parts[1].strip() else FIXED_OWNER_ID
                if key: account_list.append((key, owner))
    if not account_list: account_list.append((FIXED_API_KEY, FIXED_OWNER_ID))
    if shuffle: random.shuffle(account_list)
    return account_list

# --- ROUTES ---

@app.route('/')
def home():
    if db_error: return f"<h1>❌ Database Error</h1><p>{db_error}</p>"
    return "Deployer Service is Online 🟢. Go to <a href='/admin'>/admin</a>"

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'is_admin' not in session: return render_template('login.html')
    if request.method == 'POST':
        repo = request.form.get('repo')
        new_key = request.form.get('new_api_key').strip()
        new_owner = request.form.get('new_owner_id').strip() or FIXED_OWNER_ID
        current = get_settings().get("api_data", "")
        new_entry = f"{new_key},{new_owner}"
        updated = (current + "\n" + new_entry) if current else new_entry
        settings_col.update_one({"_id": "config"}, {"$set": {"repo": repo, "api_data": updated}}, upsert=True)
        return redirect(url_for('admin'))
    return render_template('admin.html', config=get_settings(), accounts=get_all_accounts_list())

@app.route('/admin/clear', methods=['POST'])
def admin_clear():
    if 'is_admin' not in session: return redirect(url_for('login'))
    settings_col.update_one({"_id": "config"}, {"$set": {"api_data": ""}}, upsert=True)
    return redirect(url_for('admin'))

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('password') == "admin_sudeep_123":
        session['is_admin'] = True
        return redirect(url_for('admin'))
    return "Incorrect Password"

@app.route('/prepare', methods=['POST'])
def prepare():
    data = request.form.to_dict()
    config = get_settings()
    repo_url = data.get('repo_url') or config.get('repo', 'https://github.com/TeamYukki/YukkiMusicBot')
    if 'repo_url' in data: del data['repo_url']
    return render_template('deploy.html', env_vars=data, repo_url=repo_url)

@app.route('/api/add-uptime', methods=['POST'])
def add_uptime_proxy():
    try:
        data = request.json
        url = data.get("url")
        # 40s timeout taaki sota hua bot jag jaye
        resp = requests.post(UPTIME_SERVICE_URL, json={"url": url}, timeout=40)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"status": "error", "message": f"Uptime Error: {str(e)}"})

@app.route('/api/deploy', methods=['POST'])
def deploy_api():
    try:
        accounts = get_all_accounts_list(shuffle=True)
        json_data = request.json
        repo = json_data.get('repo')
        env_vars = json_data.get('env_vars')
        
        # Prepare Env Payload (Clean List)
        env_payload = []
        for k, v in env_vars.items():
            if v: env_payload.append({"key": k, "value": str(v)})
        
        last_error = "Unknown"

        for api_key, owner_id in accounts:
            clean_owner_id = str(owner_id).strip()
            if not clean_owner_id or len(clean_owner_id) < 5: clean_owner_id = FIXED_OWNER_ID
            
            service_name = f"music-bot-{secrets.token_hex(3)}"

            # STEP 1: CREATE SERVICE (Without Env Vars first)
            create_payload = {
                "type": "web_service",
                "name": service_name,
                "ownerId": clean_owner_id, 
                "repo": repo,
                "serviceDetails": {
                    "env": "docker",
                    "region": "singapore",
                    "plan": "free"
                    # Env Vars ko hum Step 2 me bhejenge
                }
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            try:
                print(f"🔄 Creating Service... OwnerID: {clean_owner_id}")
                response = requests.post("https://api.render.com/v1/services", json=create_payload, headers=headers)
                
                if response.status_code == 201:
                    service_data = response.json()
                    srv_id = service_data.get('service', {}).get('id')
                    dash_url = f"https://dashboard.render.com/web/{srv_id}"
                    app_url = f"https://{service_name}.onrender.com"

                    # 🔥 STEP 2: FORCE PUSH ENV VARS (Double Attack Strategy)
                    print(f"🚀 Force Updating Env Vars for {srv_id}...")
                    
                    env_url = f"https://api.render.com/v1/services/{srv_id}/env-vars"
                    # PUT request purane vars ko replace karke naye daal deta hai
                    env_response = requests.put(env_url, json=env_payload, headers=headers)
                    
                    if env_response.status_code == 200:
                        print("✅ Env Vars Updated Successfully!")
                    else:
                        print(f"⚠️ Env Var Update Failed: {env_response.text}")

                    return jsonify({"status": "success", "url": dash_url, "app_url": app_url})
                
                elif response.status_code == 429:
                    print("⚠️ Rate Limit! Switching Account...")
                    continue 
                else:
                    print(f"❌ Render Creation Error: {response.text}")
                    last_error = response.text
                    continue 
            except Exception as e:
                print(f"Network Error: {e}")
                last_error = str(e)
                continue

        return jsonify({"status": "error", "message": f"All Failed. Last Error: {last_error}"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)
    
