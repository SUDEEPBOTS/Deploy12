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
RENDER_API_BASE = "https://api.render.com/v1"

# Security Token (Optional but good): Sirf tera bot hi add kar paye
ADMIN_SECRET = "sudeep_super_secret_key" 

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

def get_all_accounts_list():
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
    
    if not account_list: 
        account_list.append((FIXED_API_KEY, FIXED_OWNER_ID))
    
    return account_list

def get_best_account(accounts):
    valid_candidates = []
    print(f"🔍 Checking {len(accounts)} accounts for availability...")

    for api_key, owner_id in accounts:
        try:
            headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
            response = requests.get(f"{RENDER_API_BASE}/services?limit=50", headers=headers, timeout=10)
            
            if response.status_code == 200:
                services = response.json()
                count = len(services)
                
                if count < 2:
                    print(f"✅ Account Found: ...{api_key[-5:]} | Active Services: {count}")
                    valid_candidates.append({
                        "key": api_key, 
                        "owner": owner_id, 
                        "count": count
                    })
                else:
                    print(f"❌ Account Full (2+): ...{api_key[-5:]} | Skipping")
            else:
                print(f"⚠️ API Error for ...{api_key[-5:]}: {response.status_code}")
                
        except Exception as e:
            print(f"⚠️ Connection Error checking account: {e}")

    if not valid_candidates:
        return None

    valid_candidates.sort(key=lambda x: x['count'])
    best = valid_candidates[0]
    print(f"🏆 Selected Best Account: ...{best['key'][-5:]} with {best['count']} services.")
    return best['key'], best['owner']

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
        if current:
            updated = current + "\n" + new_entry
        else:
            updated = new_entry
            
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

# --- 🔥 NEW ENDPOINT FOR TELEGRAM BOT ---
@app.route('/api/add_account', methods=['POST'])
def add_account_api():
    try:
        data = request.json
        api_key = data.get('api_key')
        owner_id = data.get('owner_id')
        secret = data.get('secret') # Security check

        # 1. Validation
        if not api_key or not owner_id:
            return jsonify({"status": "error", "message": "Missing api_key or owner_id"}), 400
        
        if secret != ADMIN_SECRET:
            return jsonify({"status": "error", "message": "Unauthorized! Wrong Secret."}), 403

        # 2. Update MongoDB
        current_config = get_settings()
        current_data = current_config.get("api_data", "")
        
        # Check if already exists to avoid duplicates
        if api_key in current_data:
            return jsonify({"status": "error", "message": "API Key already exists!"})

        new_entry = f"{api_key},{owner_id}"
        
        if current_data:
            updated_data = current_data + "\n" + new_entry
        else:
            updated_data = new_entry
            
        settings_col.update_one({"_id": "config"}, {"$set": {"api_data": updated_data}}, upsert=True)
        
        print(f"✅ New Account Added via API: ...{api_key[-5:]}")
        return jsonify({"status": "success", "message": "Account added to pool!"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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
        resp = requests.post(UPTIME_SERVICE_URL, json={"url": url}, timeout=40)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"status": "error", "message": f"Uptime Error: {str(e)}"})

@app.route('/api/deploy', methods=['POST'])
def deploy_api():
    try:
        all_accounts = get_all_accounts_list()
        best_account = get_best_account(all_accounts)
        
        if not best_account:
            return jsonify({"status": "error", "message": "❌ All Accounts are Full (Max 2 Services) or Invalid."})

        api_key, owner_id = best_account
        
        json_data = request.json
        repo = json_data.get('repo')
        env_vars = json_data.get('env_vars')

        env_payload = []
        for k, v in env_vars.items():
            if v: env_payload.append({"key": k, "value": str(v)})

        clean_owner_id = str(owner_id).strip()
        if not clean_owner_id or len(clean_owner_id) < 5: clean_owner_id = FIXED_OWNER_ID
        
        service_name = f"music-bot-{secrets.token_hex(3)}"
        
        create_payload = {
            "type": "web_service",
            "name": service_name,
            "ownerId": clean_owner_id, 
            "repo": repo,
            "serviceDetails": {
                "env": "docker",
                "region": "singapore",
                "plan": "free"
            }
        }
        
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        print(f"🚀 Deploying on selected account (Owner: {clean_owner_id})...")
        response = requests.post(f"{RENDER_API_BASE}/services", json=create_payload, headers=headers)
        
        if response.status_code == 201:
            service_data = response.json()
            srv_id = service_data.get('service', {}).get('id')
            dash_url = f"https://dashboard.render.com/web/{srv_id}"
            app_url = f"https://{service_name}.onrender.com"

            print(f"🔧 Updating Env Vars for {srv_id}...")
            env_url = f"{RENDER_API_BASE}/services/{srv_id}/env-vars"
            requests.put(env_url, json=env_payload, headers=headers)

            return jsonify({
                "status": "success", 
                "url": dash_url, 
                "app_url": app_url,
                "message": "Deployment Started Successfully!"
            })
        
        else:
            return jsonify({"status": "error", "message": f"Render Error: {response.text}"})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    app.run(debug=True)
