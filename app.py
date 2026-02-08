from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from pymongo import MongoClient
import requests
import os
import secrets
import traceback
import random

app = Flask(__name__)
app.secret_key = "debug_secret_key_123"

# --- MONGODB SETUP ---
MONGO_URL = os.getenv("MONGO_URL")

client = None
db = None
settings_col = None
db_error = None

# 🔥 BACKUP ID: Agar DB se Owner ID na mile ya galat ho, toh ye use hogi
BACKUP_OWNER_ID = "tea-d5kdaj3e5dus73a6s9e0"

try:
    if not MONGO_URL:
        db_error = "MONGO_URL Environment Variable nahi mila! Vercel Settings check karo."
    else:
        client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        db = client["DeployerBot"]
        settings_col = db["settings"]
        client.server_info()
except Exception as e:
    db_error = str(e)

# --- HELPER: GET SETTINGS ---
def get_settings():
    if settings_col is None:
        return {"repo": "", "api_data": ""}
    try:
        data = settings_col.find_one({"_id": "config"})
        return data if data else {"repo": "", "api_data": ""}
    except:
        return {"repo": "", "api_data": ""}

# --- HELPER: PARSE ACCOUNTS (Robust Logic) ---
def get_all_accounts_list(shuffle=False):
    config = get_settings()
    raw_data = config.get("api_data", "")
    
    account_list = []
    
    # Agar DB khali hai, toh kam se kam Backup ID ke sath ek dummy entry bhej do
    # (Par API key chahiye hogi, isliye hum assume karte hain user ne DB fill kiya hai)
    if not raw_data:
        return []

    # Line by line split karo
    lines = [line.strip() for line in raw_data.split('\n') if line.strip()]
    
    for line in lines:
        parts = line.split(',')
        if len(parts) >= 1:
            key = parts[0].strip()
            
            # Agar Owner ID hai toh use karo, warna BACKUP use karo
            if len(parts) >= 2 and parts[1].strip():
                owner = parts[1].strip()
            else:
                owner = BACKUP_OWNER_ID
            
            if key:
                account_list.append((key, owner))
    
    if shuffle:
        random.shuffle(account_list)
        
    return account_list

# --- ROUTES ---

@app.route('/')
def home():
    if db_error:
        return f"<h1>❌ Database Error</h1><p>{db_error}</p>"
    return "Deployer Service is Online 🟢. Go to <a href='/admin'>/admin</a>"

# --- ADMIN: SHOW PAGE ---
@app.route('/admin', methods=['GET'])
def admin():
    if 'is_admin' not in session:
        return render_template('login.html')
    
    config = get_settings()
    accounts = get_all_accounts_list(shuffle=False)
    
    return render_template('admin.html', config=config, accounts=accounts)

# --- ADMIN: ADD ACCOUNT ---
@app.route('/admin/add', methods=['POST'])
def admin_add():
    if 'is_admin' not in session: return redirect(url_for('login'))
    if settings_col is None: return "Database Error"

    repo = request.form.get('repo')
    new_key = request.form.get('new_api_key').strip()
    new_owner = request.form.get('new_owner_id').strip()

    # Agar user ne Owner ID nahi daali, toh Backup ID save kar lo
    if not new_owner:
        new_owner = BACKUP_OWNER_ID

    current_config = get_settings()
    current_api_data = current_config.get("api_data", "")
    new_entry = f"{new_key},{new_owner}"

    if current_api_data:
        updated_api_data = current_api_data + "\n" + new_entry
    else:
        updated_api_data = new_entry

    settings_col.update_one(
        {"_id": "config"}, 
        {"$set": {"repo": repo, "api_data": updated_api_data}}, 
        upsert=True
    )
    return redirect(url_for('admin'))

# --- ADMIN: CLEAR ALL ---
@app.route('/admin/clear', methods=['POST'])
def admin_clear():
    if 'is_admin' not in session: return redirect(url_for('login'))
    if settings_col is not None:
        settings_col.update_one(
            {"_id": "config"}, 
            {"$set": {"api_data": ""}},
            upsert=True
        )
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
    repo_url = data.get('repo_url')
    if not repo_url:
        repo_url = config.get('repo', 'https://github.com/TeamYukki/YukkiMusicBot')
    
    if 'repo_url' in data: del data['repo_url']
    return render_template('deploy.html', env_vars=data, repo_url=repo_url)

@app.route('/api/deploy', methods=['POST'])
def deploy_api():
    try:
        accounts = get_all_accounts_list(shuffle=True)

        if not accounts:
            return jsonify({"status": "error", "message": "Admin Panel khali hai! Accounts add karo."})

        json_data = request.json
        repo = json_data.get('repo')
        env_vars = json_data.get('env_vars')
        
        env_payload = [{"key": k, "value": v} for k, v in env_vars.items()]
        
        last_error = "Unknown Error"

        # --- LOOP THROUGH ACCOUNTS ---
        for api_key, owner_id in accounts:
            
            # Extra Safety: Agar Owner ID khali hai to Backup use karo
            if not owner_id or len(owner_id) < 5:
                owner_id = BACKUP_OWNER_ID

            payload = {
                "serviceDetails": {
                    "type": "web_service",
                    "name": f"music-bot-{secrets.token_hex(3)}",
                    "repo": repo,
                    "env": "docker",
                    "region": "singapore",
                    "plan": "free",
                    "ownerId": str(owner_id),
                    "envVars": env_payload
                }
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }

            try:
                print(f"🔄 Trying Key: ...{api_key[-4:]} | Owner: {owner_id}")
                response = requests.post("https://api.render.com/v1/services", json=payload, headers=headers)
                
                # CASE 1: SUCCESS ✅
                if response.status_code == 201:
                    service_data = response.json()
                    srv_id = service_data.get('service', {}).get('id')
                    dash_url = f"https://dashboard.render.com/web/{srv_id}"
                    return jsonify({"status": "success", "url": dash_url})
                
                # CASE 2: RATE LIMIT ⚠️ (Try Next)
                elif response.status_code == 429:
                    print("⚠️ Rate Limit Hit! Switching to next account...")
                    last_error = "Rate Limit Exceeded on this key."
                    continue 
                
                # CASE 3: OTHER ERROR ❌ (Try Next - Shayad Owner ID galat ho, dusri key chal jaye)
                else:
                    print(f"❌ Render Error: {response.text}")
                    last_error = f"Render Error: {response.text}"
                    continue # <--- YAHAN CHANGE KIYA HAI (Pehle 'return' tha)

            except Exception as e:
                print(f"❌ Connection Error: {e}")
                last_error = str(e)
                continue

        # Agar loop khatam ho gaya aur koi success nahi mili
        return jsonify({"status": "error", "message": f"All accounts failed. Last Error: {last_error}"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)
