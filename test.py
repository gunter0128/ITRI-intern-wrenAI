import requests
import json

# ⚠️ 替換成您的實際值
# -----------------------------------------------
WREN_API_KEY = "sk-DBCCrxB1okbA" 
PROJECT_ID = "11237"
# -----------------------------------------------

# 構建目標 URL，將 {projectId} 替換為實際的 Project ID
url = f"https://cloud.getwren.ai/api/v1/projects/{PROJECT_ID}"

# 設置 Headers，必須包含 Authorization (Bearer Token)
headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {WREN_API_KEY}" 
}

print(f"嘗試請求 URL: {url}")

# --- 執行 GET 請求 ---
try:
    response = requests.get(url, headers=headers, timeout=10)
    status_code = response.status_code

    if 200 <= status_code < 300:
        print("\n✅ 請求成功！狀態碼: 200 OK")
        print("---------------------------------")
        # 打印格式化的 JSON 響應
        print(json.dumps(response.json(), indent=2))
        
    else:
        # 處理失敗的請求
        print(f"\n❌ 請求失敗！狀態碼: {status_code}")
        print("---------------------------------")
        print("詳細錯誤信息:")
        try:
            error_data = response.json()
            error_msg = error_data.get('error', '無法解析錯誤詳情')
            print(f"Wren API 錯誤: {error_msg}")
            print(json.dumps(error_data, indent=2))
        except json.JSONDecodeError:
            print("無法解析 JSON，原始文本:", response.text)

except requests.exceptions.RequestException as e:
    print(f"\n⚠️ 發生網絡或連線錯誤: {e}")